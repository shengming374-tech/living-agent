"""Agent feedback, cancellation and same-process recovery regressions."""

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from living_agent.agent.repository import AgentConflictError
from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.execution.contracts import TaskRunStatus, TaskStepStatus
from living_agent.models.events import IngressEnvelope, SourceType
from living_agent.models.psyche import ActivityStatus
from living_agent.providers.llm import MockLLMProvider, ModelResponse
from living_agent.trust.boundary import TrustBoundary

OWNER = {"X-Actor-ID": "owner-1"}


class DecisionProvider(MockLLMProvider):
    def __init__(self, decide: Callable[[dict[str, Any], list[dict[str, Any]]], Any]) -> None:
        super().__init__()
        self.decide = decide

    async def generate(self, context: CompiledContext) -> ModelResponse:
        task = next(
            (
                json.loads(section.content)
                for section in context.sections
                if section.kind is ContextKind.CURRENT_TASK
            ),
            {},
        )
        if task.get("agent_protocol") != 1:
            return await super().generate(context)
        observations = [
            json.loads(section.content)
            for section in context.sections
            if section.kind is ContextKind.UNTRUSTED_TOOL_RESULT
        ]
        decision = self.decide(task, observations)
        return ModelResponse(
            text=decision if isinstance(decision, str) else json.dumps(decision),
            provider="scripted",
        )


def tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"action": "tool", "summary": "执行下一步", "tool": name, "arguments": arguments}


def finish(observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "action": "finish",
        "summary": "结果已核对",
        "evidence_task_ids": [
            item["task_id"] for item in observations if item["status"] == "completed"
        ],
    }


def config(settings: Settings, tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("initial", encoding="utf-8")
    return settings.model_copy(update={"work_workspace_root": workspace})


def start(client: TestClient, goal: str = "检查工作区并读取 README") -> dict[str, Any]:
    response = client.post("/v1/agent/runs", headers=OWNER, json={"goal": goal})
    assert response.status_code == 200, response.text
    return response.json()


def test_mock_recovers_missing_readme_from_supplied_path(
    settings: Settings, tmp_path: Path
) -> None:
    settings = config(settings, tmp_path)
    (settings.work_workspace_root / "README.md").unlink()
    (settings.work_workspace_root / "GUIDE.md").write_text("A real guide", encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        run = start(client)
        assert run["status"] == "waiting_input"
        result = client.post(
            f"/v1/agent/runs/{run['run_id']}/resume",
            headers=OWNER,
            json={"message": " GUIDE.md "},
        ).json()
        assert result["status"] == "completed", result
        assert result["input_notes"] == ["GUIDE.md"]
        assert result["observations"][-1]["arguments"]["path"] == "GUIDE.md"
        assert "A real guide" in result["summary"]


def test_model_receives_question_and_failed_action_arguments(
    settings: Settings, tmp_path: Path
) -> None:
    def decide(task: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
        if not observations:
            return tool("workspace_read", path="missing.md")
        if not task["input_notes"]:
            assert observations[-1]["arguments"]["path"] == "missing.md"
            return {"action": "ask", "summary": "应改为读取哪个文件?"}
        assert task["last_question"] == "应改为读取哪个文件?"
        if observations[-1]["status"] == "failed":
            return tool("workspace_read", path=task["input_notes"][-1])
        return finish(observations)

    with TestClient(
        create_app(config(settings, tmp_path), llm_provider=DecisionProvider(decide))
    ) as client:
        run = start(client)
        result = client.post(
            f"/v1/agent/runs/{run['run_id']}/resume", headers=OWNER, json={"message": "README.md"}
        ).json()
        assert result["status"] == "completed", result


def test_rereading_after_writes_is_progress(settings: Settings, tmp_path: Path) -> None:
    def decide(task: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
        if len(observations) == 5:
            return finish(observations)
        if len(observations) % 2 == 0:
            return tool("workspace_read", path="README.md")
        return tool("workspace_write", path="README.md", content=f"version {len(observations)}")

    with TestClient(
        create_app(config(settings, tmp_path), llm_provider=DecisionProvider(decide))
    ) as client:
        run = start(client)
        for _ in range(2):
            assert run["status"] == "waiting_confirmation", run
            run = client.post(f"/v1/agent/runs/{run['run_id']}/confirm", headers=OWNER).json()
        assert run["status"] == "completed", run
        assert run["observations"][-1]["output"]["text"] == "version 3"


def test_equivalent_default_arguments_cannot_evade_repeat_limit(
    settings: Settings, tmp_path: Path
) -> None:
    def decide(task: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
        arguments: dict[str, Any] = {"path": "."}
        if len(observations) == 1:
            arguments.update(recursive=False, max_entries=200)
        return tool("workspace_list", **arguments)

    with TestClient(
        create_app(config(settings, tmp_path), llm_provider=DecisionProvider(decide))
    ) as client:
        run = start(client)
        assert run["status"] == "failed"
        assert run["error_code"] == "repeated_action_without_progress"
        assert run["pending_proposal"] is None
        assert len(run["observations"]) == 2


@pytest.mark.parametrize(
    ("decision", "error_code"),
    [
        ("{broken JSON", "model_response_invalid_json"),
        (tool("unknown_tool"), "unknown_agent_tool"),
        (tool("workspace_read", path="README.md", forged=True), "model_decision_invalid"),
        ({"action": "finish", "summary": "没有证据"}, "finish_requires_observed_evidence"),
    ],
)
def test_failures_have_safe_actionable_reason_codes(
    settings: Settings, tmp_path: Path, decision: Any, error_code: str
) -> None:
    provider = DecisionProvider(lambda task, observations: decision)
    with TestClient(create_app(config(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "failed"
        assert run["error_code"] == error_code


@pytest.mark.parametrize("goal", [" ", "\n\t"])
def test_blank_goals_are_rejected(settings: Settings, tmp_path: Path, goal: str) -> None:
    with TestClient(create_app(config(settings, tmp_path))) as client:
        assert client.post("/v1/agent/runs", headers=OWNER, json={"goal": goal}).status_code == 422
        assert client.get("/v1/agent/runs", headers=OWNER).json() == []


def test_goal_is_normalized_before_event_persistence(settings: Settings, tmp_path: Path) -> None:
    with TestClient(create_app(config(settings, tmp_path))) as client:
        run = start(client, "  检查工作区并读取 README  ")
        assert run["goal"] == run["event"]["content"] == "检查工作区并读取 README"


def test_resume_during_waiting_state_checkpoint_does_not_leave_running_run(
    settings: Settings, tmp_path: Path
) -> None:
    provider = DecisionProvider(
        lambda task, observations: (
            finish(observations)
            if observations
            else tool("workspace_read", path=task["input_notes"][-1])
            if task["input_notes"]
            else {"action": "ask", "summary": "请指定文件"}
        )
    )
    with TestClient(create_app(config(settings, tmp_path), llm_provider=provider)) as client:

        async def exercise() -> None:
            entered, release = asyncio.Event(), asyncio.Event()
            service = client.app.state.agent_service
            original = service._record

            async def delayed_record(run: Any, outcome: str) -> None:
                if outcome == "waiting_input":
                    entered.set()
                    await release.wait()
                await original(run, outcome)

            service._record = delayed_record
            event = TrustBoundary(client.app.state.authority).normalize(
                IngressEnvelope(
                    content="inspect",
                    source_type=SourceType.DIRECT_MESSAGE,
                    source_identity="owner-1",
                    authenticated=True,
                    conversation_id="resume-race",
                )
            )
            await client.app.state.event_repository.add(event)
            request = asyncio.create_task(service.start(event, "inspect"))
            await entered.wait()
            run = (await service.repository.list_runs())[0]
            with pytest.raises(AgentConflictError):
                await service.resume(run.run_id, actor_id="owner-1", message="README.md")
            assert (await service.repository.get(run.run_id)).status == "waiting_input"
            release.set()
            assert (await request).status == "waiting_input"
            result = await service.resume(run.run_id, actor_id="owner-1", message="README.md")
            assert result.status == "completed"

        client.portal.call(exercise)


@pytest.mark.parametrize("outcome", ["started", "resumed"])
def test_lifecycle_audit_interruption_leaves_resumable_checkpoint(
    settings: Settings, tmp_path: Path, outcome: str
) -> None:
    provider = DecisionProvider(
        lambda task, observations: {"action": "ask", "summary": "请指定文件"}
    )
    with TestClient(create_app(config(settings, tmp_path), llm_provider=provider)) as client:

        async def exercise() -> None:
            entered = asyncio.Event()
            service = client.app.state.agent_service
            original = service._record
            event = TrustBoundary(client.app.state.authority).normalize(
                IngressEnvelope(
                    content="inspect",
                    source_type=SourceType.DIRECT_MESSAGE,
                    source_identity="owner-1",
                    authenticated=True,
                    conversation_id="audit-interrupt",
                )
            )
            await client.app.state.event_repository.add(event)
            existing = await service.start(event, "inspect") if outcome == "resumed" else None

            async def delayed_record(run: Any, lifecycle: str) -> None:
                if lifecycle == outcome:
                    entered.set()
                    await asyncio.Event().wait()
                await original(run, lifecycle)

            service._record = delayed_record
            request = asyncio.create_task(
                service.resume(existing.run_id, actor_id="owner-1", message="README.md")
                if existing is not None
                else service.start(event, "inspect")
            )
            await entered.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            run = (await service.repository.list_runs())[0]
            assert run.status == "paused"
            assert run.error_code == "request_interrupted"
            assert not service._drivers

        client.portal.call(exercise)


def test_request_interruption_recovers_child_in_same_process(
    settings: Settings, tmp_path: Path
) -> None:
    provider = DecisionProvider(
        lambda task, observations: (
            finish(observations)
            if observations and observations[-1]["status"] == "completed"
            else tool("workspace_read", path="README.md")
        )
    )
    with TestClient(create_app(config(settings, tmp_path), llm_provider=provider)) as client:

        async def exercise() -> None:
            entered = asyncio.Event()
            work = client.app.state.work_executor
            original = work._dispatch

            async def interrupted_dispatch(action: Any) -> Any:
                entered.set()
                await asyncio.Event().wait()

            work._dispatch = interrupted_dispatch
            service = client.app.state.agent_service
            event = TrustBoundary(client.app.state.authority).normalize(
                IngressEnvelope(
                    content="inspect",
                    source_type=SourceType.DIRECT_MESSAGE,
                    source_identity="owner-1",
                    authenticated=True,
                    conversation_id="recover-test",
                )
            )
            await client.app.state.event_repository.add(event)
            request = asyncio.create_task(service.start(event, "inspect"))
            await entered.wait()
            run = (await service.repository.list_runs())[0]
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            work._dispatch = original
            saved = await service.repository.get(run.run_id)
            assert saved.status == "paused"
            assert saved.pending_proposal is not None
            result = await service.resume(run.run_id, actor_id="owner-1")
            assert result.status == "completed"
            assert [item.status for item in result.observations] == ["failed", "completed"]
            tasks = await client.app.state.task_service.list(status=None, limit=100)
            assert all(
                item.status in {TaskRunStatus.FAILED, TaskRunStatus.COMPLETED} for item in tasks
            )
            assert not service._drivers
            activities = await client.app.state.psyche_service.activities()
            assert all(item.status is not ActivityStatus.RUNNING for item in activities)

        client.portal.call(exercise)


def test_cancel_before_child_creation_finishes_started_activity(
    settings: Settings, tmp_path: Path
) -> None:
    provider = DecisionProvider(lambda task, observations: tool("workspace_read", path="README.md"))
    with TestClient(create_app(config(settings, tmp_path), llm_provider=provider)) as client:

        async def exercise() -> None:
            entered = asyncio.Event()

            async def delayed_submit(proposal: Any, *, activity_id: str) -> None:
                entered.set()
                await asyncio.Event().wait()

            client.app.state.task_kernel.submit = delayed_submit
            service = client.app.state.agent_service
            event = TrustBoundary(client.app.state.authority).normalize(
                IngressEnvelope(
                    content="inspect",
                    source_type=SourceType.DIRECT_MESSAGE,
                    source_identity="owner-1",
                    authenticated=True,
                    conversation_id="cancel-before-child",
                )
            )
            await client.app.state.event_repository.add(event)
            request = asyncio.create_task(service.start(event, "inspect"))
            await entered.wait()
            run = (await service.repository.list_runs())[0]
            assert (await service.cancel(run.run_id, actor_id="owner-1")).status == "cancelled"
            stopped = await request
            assert stopped.status == "cancelled"
            assert stopped.pending_proposal is None
            assert not await client.app.state.task_service.list(status=None, limit=100)
            activities = await client.app.state.psyche_service.activities()
            assert len(activities) == 1
            assert activities[0].status is ActivityStatus.FAILED

        client.portal.call(exercise)


def test_request_interruption_preserves_confirmed_write_result(
    settings: Settings, tmp_path: Path
) -> None:
    settings = config(settings, tmp_path)
    provider = DecisionProvider(
        lambda task, observations: (
            finish(observations)
            if observations
            else tool("workspace_write", path="saved.txt", content="once")
        )
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        run = start(client)

        async def exercise() -> None:
            entered = asyncio.Event()
            release = asyncio.Event()
            work = client.app.state.work_executor
            original = work._dispatch

            async def interrupted_dispatch(action: Any) -> Any:
                entered.set()
                await release.wait()
                return await original(action)

            work._dispatch = interrupted_dispatch
            service = client.app.state.agent_service
            request = asyncio.create_task(
                service.resume(run["run_id"], actor_id="owner-1", confirm=True)
            )
            await entered.wait()
            request.cancel()
            await asyncio.sleep(0)
            request.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            work._dispatch = original
            assert (await service.repository.get(run["run_id"])).status == "paused"
            completed = await service.resume(run["run_id"], actor_id="owner-1")
            assert completed.status == "completed"
            assert (settings.work_workspace_root / "saved.txt").read_text() == "once"
            assert len(await client.app.state.task_service.list(status=None, limit=100)) == 1

        client.portal.call(exercise)


def test_orphaned_write_requires_confirmation_before_recovery(
    settings: Settings, tmp_path: Path
) -> None:
    settings = config(settings, tmp_path)
    provider = DecisionProvider(
        lambda task, observations: (
            finish(observations)
            if observations
            else tool("workspace_write", path="saved.txt", content="once")
        )
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        run = start(client)

        async def exercise() -> None:
            service = client.app.state.agent_service
            child_id = run["pending_proposal"]["task"]["task_id"]
            child = await client.app.state.task_service.get(child_id)
            child.status = TaskRunStatus.RUNNING
            child.step_results[0].status = TaskStepStatus.RUNNING
            child.step_results[0].attempts = 1
            await client.app.state.task_repository.save(child)
            parent = await service.repository.get(run["run_id"])
            parent.status = "paused"
            await service.repository.save(parent)
            resumed = await service.resume(run["run_id"], actor_id="owner-1")
            assert resumed.status == "waiting_confirmation"
            assert not (settings.work_workspace_root / "saved.txt").exists()
            completed = await service.resume(run["run_id"], actor_id="owner-1", confirm=True)
            assert completed.status == "completed"
            assert (settings.work_workspace_root / "saved.txt").read_text() == "once"
            assert len(await client.app.state.task_service.list(status=None, limit=100)) == 1

        client.portal.call(exercise)


def test_cancel_waits_for_writing_thread_and_preserves_evidence(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = config(settings, tmp_path)
    provider = DecisionProvider(
        lambda task, observations: tool("workspace_write", path="saved.txt", content="once")
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        run = start(client)

        async def exercise() -> None:
            entered, release = threading.Event(), threading.Event()
            work = client.app.state.work_executor
            original = work._write_file

            def blocked_write(arguments: Any) -> Any:
                entered.set()
                assert release.wait(timeout=5)
                return original(arguments)

            monkeypatch.setattr(work, "_write_file", blocked_write)
            service = client.app.state.agent_service
            checkpoint = asyncio.Event()
            original_save = service.repository.save

            async def save_checkpoint(run: Any) -> Any:
                saved = await original_save(run)
                if saved.status == "cancelled":
                    checkpoint.set()
                return saved

            monkeypatch.setattr(service.repository, "save", save_checkpoint)
            request = asyncio.create_task(
                service.resume(run["run_id"], actor_id="owner-1", confirm=True)
            )
            assert await asyncio.to_thread(entered.wait, 2)
            cancellation = asyncio.create_task(service.cancel(run["run_id"], actor_id="owner-1"))
            await asyncio.wait_for(checkpoint.wait(), timeout=2)
            assert not cancellation.done()
            release.set()
            cancelled = await cancellation
            assert cancelled.status == "cancelled"
            stopped = await request
            assert stopped.status == "cancelled"
            assert stopped.observations[-1].evidence_kinds
            assert cancelled.observations[-1].status == "completed"
            assert cancelled.observations[-1].evidence_kinds
            assert cancelled.pending_proposal is None
            assert (settings.work_workspace_root / "saved.txt").read_text() == "once"
            assert not service._drivers

        client.portal.call(exercise)


def test_cancelling_running_shell_terminates_process_and_child(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = config(settings, tmp_path).model_copy(
        update={"work_shell_enabled": True, "work_shell_allowed_executables": ["sleep"]}
    )
    provider = DecisionProvider(
        lambda task, observations: tool("shell_execute", argv=["sleep", "30"])
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        run = start(client)

        async def exercise() -> None:
            entered = asyncio.Event()
            processes: list[asyncio.subprocess.Process] = []
            original = asyncio.create_subprocess_exec

            async def capture_process(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
                process = await original(*args, **kwargs)
                processes.append(process)
                entered.set()
                return process

            monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_process)
            service = client.app.state.agent_service
            request = asyncio.create_task(
                service.resume(run["run_id"], actor_id="owner-1", confirm=True)
            )
            await entered.wait()
            cancelled = await service.cancel(run["run_id"], actor_id="owner-1")
            assert cancelled.status == "cancelled"
            assert (await request).status == "cancelled"
            assert processes[0].returncode is not None
            child_id = run["pending_proposal"]["task"]["task_id"]
            assert (
                await client.app.state.task_service.get(child_id)
            ).status is TaskRunStatus.CANCELLED
            assert not service._drivers
            activities = await client.app.state.psyche_service.activities()
            assert all(item.status is not ActivityStatus.RUNNING for item in activities)

        client.portal.call(exercise)


def test_recovery_uses_current_child_state_instead_of_stale_snapshot(
    settings: Settings, tmp_path: Path
) -> None:
    settings = config(settings, tmp_path)
    provider = DecisionProvider(
        lambda task, observations: tool("workspace_write", path="saved.txt", content="once")
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        run = start(client)

        async def exercise() -> None:
            tasks = client.app.state.task_service
            child_id = run["pending_proposal"]["task"]["task_id"]
            stale = await tasks.get(child_id)
            stale.status = TaskRunStatus.RUNNING
            await tasks.confirm(task_id=child_id, conversation_id=None, actor_id="owner-1")
            (settings.work_workspace_root / "saved.txt").write_text("external change")
            recovered = await client.app.state.task_kernel.recover(stale)
            assert recovered.status is TaskRunStatus.COMPLETED
            assert (settings.work_workspace_root / "saved.txt").read_text() == "external change"

        client.portal.call(exercise)
