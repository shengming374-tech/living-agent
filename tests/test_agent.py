"""真实工具和持久化驱动的验收。 / Acceptance through real tools and persistence."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.providers.llm import MockLLMProvider, ModelResponse

OWNER = {"X-Actor-ID": "owner-1"}


class ScriptedProvider(MockLLMProvider):
    def __init__(self, decide: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> None:
        super().__init__()
        self.decide = decide
        self.contexts: list[CompiledContext] = []

    async def generate(self, context: CompiledContext) -> ModelResponse:
        tasks = [
            json.loads(s.content) for s in context.sections if s.kind is ContextKind.CURRENT_TASK
        ]
        if not tasks or tasks[0].get("agent_protocol") != 1:
            return await super().generate(context)
        self.contexts.append(context)
        observations = [
            json.loads(s.content)
            for s in context.sections
            if s.kind is ContextKind.UNTRUSTED_TOOL_RESULT
        ]
        return ModelResponse(text=json.dumps(self.decide(observations)), provider="scripted")


def tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"action": "tool", "summary": "下一步", "tool": name, "arguments": arguments}


def finish(observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "action": "finish",
        "summary": "已完成并有文件证据",
        "evidence_task_ids": [
            item["task_id"] for item in observations if item["status"] == "completed"
        ],
    }


def configured(settings: Settings, tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "README.md").write_text("# Agent acceptance\nPersistent local project.\n")
    return settings.model_copy(update={"work_workspace_root": workspace})


def start(client: TestClient, goal: str = "检查工作区并读取 README") -> dict[str, Any]:
    response = client.post("/v1/agent/runs", headers=OWNER, json={"goal": goal})
    assert response.status_code == 200, response.text
    return response.json()


def test_mock_observes_directory_then_reads_and_finishes(
    settings: Settings, tmp_path: Path
) -> None:
    with TestClient(create_app(configured(settings, tmp_path))) as client:
        run = start(client)
        assert run["status"] == "completed", run
        assert run["iterations"] == 3
        assert [item["tool"] for item in run["observations"]] == [
            "workspace_list",
            "workspace_read",
        ]
        assert "Agent acceptance" in run["summary"]
        assert all(item["evidence_kinds"] for item in run["observations"])
        assert client.get(f"/v1/agent/runs/{run['run_id']}", headers=OWNER).json() == run
        assert len(client.get("/v1/agent/tools", headers=OWNER).json()) == 11


def test_model_uses_observation_to_repair_failed_path(settings: Settings, tmp_path: Path) -> None:
    def decide(observations: list[dict[str, Any]]) -> dict[str, Any]:
        if not observations:
            return tool("workspace_read", path="missing.md")
        if len(observations) == 1:
            assert observations[0]["status"] == "failed"
            return tool("workspace_read", path="README.md")
        return finish(observations)

    provider = ScriptedProvider(decide)
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "completed", run
        assert [item["status"] for item in run["observations"]] == ["failed", "completed"]
        for context in provider.contexts[1:]:
            results = [s for s in context.sections if s.kind is ContextKind.UNTRUSTED_TOOL_RESULT]
            assert results and all("untrusted_tool_result" in s.taint_labels for s in results)
            assert all(s.source_event_ids for s in results)


def test_write_waits_for_exact_confirmation_then_continues(
    settings: Settings, tmp_path: Path
) -> None:
    provider = ScriptedProvider(
        lambda obs: (
            finish(obs) if obs else tool("workspace_write", path="note.txt", content="real output")
        )
    )
    config = configured(settings, tmp_path)
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client, "保存说明")
        assert run["status"] == "waiting_confirmation", run
        assert not (config.work_workspace_root / "note.txt").exists()
        child_id = run["pending_proposal"]["task"]["task_id"]
        resumed = client.post(
            f"/v1/agent/runs/{run['run_id']}/resume", headers=OWNER, json={}
        ).json()
        assert resumed["status"] == "waiting_confirmation"
        assert not (config.work_workspace_root / "note.txt").exists()
        assert resumed["pending_proposal"]["task"]["task_id"] == child_id
        confirmed = client.post(f"/v1/agent/runs/{run['run_id']}/confirm", headers=OWNER).json()
        assert confirmed["status"] == "completed", confirmed
        assert (config.work_workspace_root / "note.txt").read_text() == "real output"
        assert len(client.get("/v1/tasks", headers=OWNER).json()) == 1
        assert (
            client.post(f"/v1/agent/runs/{run['run_id']}/confirm", headers=OWNER).status_code == 409
        )


def test_restart_keeps_pending_action_and_does_not_replay_write(
    settings: Settings, tmp_path: Path
) -> None:
    config = configured(settings, tmp_path)
    provider = ScriptedProvider(
        lambda obs: (
            finish(obs) if obs else tool("workspace_write", path="saved.txt", content="once")
        )
    )
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client, "保存文件")
    assert not (config.work_workspace_root / "saved.txt").exists()
    with TestClient(create_app(config, llm_provider=provider)) as client:
        recovered = client.get(f"/v1/agent/runs/{run['run_id']}", headers=OWNER).json()
        assert recovered["pending_proposal"] == run["pending_proposal"]
        result = client.post(f"/v1/agent/runs/{run['run_id']}/confirm", headers=OWNER).json()
        assert result["status"] == "completed", result
        assert len(client.get("/v1/tasks", headers=OWNER).json()) == 1


def test_cancel_pending_goal_cancels_child(settings: Settings, tmp_path: Path) -> None:
    config = configured(settings, tmp_path)
    provider = ScriptedProvider(lambda obs: tool("workspace_write", path="no.txt", content="no"))
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client)
        result = client.post(f"/v1/agent/runs/{run['run_id']}/cancel", headers=OWNER).json()
        assert result["status"] == "cancelled"
        child_id = run["pending_proposal"]["task"]["task_id"]
        assert client.get(f"/v1/tasks/{child_id}", headers=OWNER).json()["status"] == "cancelled"
        assert not (config.work_workspace_root / "no.txt").exists()


@pytest.mark.parametrize(
    "decision",
    [
        {"action": "finish", "summary": "已写入", "evidence_task_ids": ["invented"]},
        {"action": "tool", "summary": "越权", "tool": "delete_everything", "arguments": {}},
        {
            "action": "tool",
            "summary": "伪造",
            "tool": "workspace_list",
            "arguments": {"path": "."},
            "actor_id": "owner-1",
        },
        tool("workspace_read", path="README.md", capability="anything"),
    ],
)
def test_invalid_model_decisions_fail_closed(
    settings: Settings, tmp_path: Path, decision: dict[str, Any]
) -> None:
    with TestClient(
        create_app(
            configured(settings, tmp_path), llm_provider=ScriptedProvider(lambda obs: decision)
        )
    ) as client:
        run = start(client)
        assert run["status"] == "failed", run
        assert not client.get("/v1/tasks", headers=OWNER).json()


def test_workspace_escape_produces_failure_evidence(settings: Settings, tmp_path: Path) -> None:
    provider = ScriptedProvider(
        lambda obs: (
            {"action": "ask", "summary": "请提供有效路径"}
            if obs
            else tool("workspace_read", path="../secret.txt")
        )
    )
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "waiting_input"
        assert run["observations"][0]["status"] == "failed"
        assert run["observations"][0]["output"] is None


def test_iteration_and_repeat_budgets(settings: Settings, tmp_path: Path) -> None:
    config = configured(settings, tmp_path).model_copy(update={"agent_max_iterations": 2})
    provider = ScriptedProvider(lambda obs: tool("workspace_list", path="."))
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "failed"
        assert run["error_code"] == "iteration_budget_exhausted"
        assert len(run["observations"]) == 2
    config = config.model_copy(update={"agent_max_iterations": 8})
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "failed"
        assert run["iterations"] == 3
        assert len(run["observations"]) == 2


def test_ask_requires_input_and_preserves_lifetime_budget(
    settings: Settings, tmp_path: Path
) -> None:
    provider = ScriptedProvider(lambda obs: {"action": "ask", "summary": "请指定文件"})
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        path = f"/v1/agent/runs/{run['run_id']}/resume"
        assert client.post(path, headers=OWNER, json={}).status_code == 409
        resumed = client.post(path, headers=OWNER, json={"message": "README.md"}).json()
        assert resumed["iterations"] == 2
        assert resumed["input_notes"] == ["README.md"]


def test_owner_auth_and_chat_routing(settings: Settings, tmp_path: Path) -> None:
    with TestClient(create_app(configured(settings, tmp_path))) as client:
        assert (
            client.post(
                "/v1/agent/runs", headers={"X-Actor-ID": "member"}, json={"goal": "read"}
            ).status_code
            == 403
        )
        for actor in ["member", "owner-1"]:
            reply = client.post(
                "/v1/chat",
                json={
                    "content": "agent: 检查工作区并读取 README",
                    "source_type": "direct_message",
                    "source_identity": actor,
                    "conversation_id": "chat",
                    "authenticated": True,
                },
            ).json()
            if actor == "member":
                assert reply["agent_run_id"] is None
            else:
                assert reply["agent_run_id"]
                assert "Agent acceptance" in " ".join(reply["messages"])
        ordinary = client.post(
            "/v1/chat",
            json={
                "content": "你好",
                "source_type": "direct_message",
                "source_identity": "owner-1",
                "conversation_id": "chat",
                "authenticated": True,
            },
        ).json()
        assert ordinary["agent_run_id"] is None


def test_agent_api_requires_management_bearer(settings: Settings, tmp_path: Path) -> None:
    from pydantic import SecretStr

    config = configured(settings, tmp_path).model_copy(
        update={
            "management_api_token": SecretStr("a" * 40),
        }
    )
    with TestClient(create_app(config)) as client:
        assert client.get("/v1/agent/runs", headers=OWNER).status_code == 401
        assert (
            client.get(
                "/v1/agent/runs", headers={**OWNER, "Authorization": "Bearer " + "a" * 40}
            ).status_code
            == 200
        )


def test_restart_reconciles_completed_child_without_replaying(
    settings: Settings, tmp_path: Path
) -> None:
    config = configured(settings, tmp_path)
    provider = ScriptedProvider(
        lambda obs: (
            finish(obs) if obs else tool("workspace_write", path="once.txt", content="original")
        )
    )
    with TestClient(create_app(config, llm_provider=provider)) as client:
        run = start(client)
        child_id = run["pending_proposal"]["task"]["task_id"]
        # Model a crash after the child's commit, before the parent's observation checkpoint.
        assert (
            client.post(f"/v1/tasks/{child_id}/confirm", headers=OWNER).json()["status"]
            == "completed"
        )

        async def interrupt_checkpoint() -> None:
            repo = client.app.state.agent_service.repository
            saved = await repo.get(run["run_id"])
            saved.status = "running"
            await repo.save(saved)

        client.portal.call(interrupt_checkpoint)
    (config.work_workspace_root / "once.txt").write_text("external change")
    with TestClient(create_app(config, llm_provider=provider)) as client:
        recovered = client.get(f"/v1/agent/runs/{run['run_id']}", headers=OWNER).json()
        assert recovered["status"] == "paused"
        resumed = client.post(
            f"/v1/agent/runs/{run['run_id']}/resume", headers=OWNER, json={}
        ).json()
        assert resumed["status"] == "completed"
        assert (config.work_workspace_root / "once.txt").read_text() == "external change"
        assert len(client.get("/v1/tasks", headers=OWNER).json()) == 1


def test_cancellation_wins_over_inflight_model_decision(settings: Settings, tmp_path: Path) -> None:
    import asyncio

    from living_agent.agent.contracts import AgentDecision
    from living_agent.models.events import IngressEnvelope, SourceType
    from living_agent.trust.boundary import TrustBoundary

    with TestClient(create_app(configured(settings, tmp_path))) as client:

        async def exercise() -> None:
            entered, release = asyncio.Event(), asyncio.Event()

            class SlowPlanner:
                async def decide(self, run: Any) -> AgentDecision:
                    entered.set()
                    await release.wait()
                    return AgentDecision(
                        action="tool",
                        summary="stale",
                        tool="workspace_list",
                        arguments={"path": "."},
                    )

            service = client.app.state.agent_service
            service._planner = SlowPlanner()
            event = TrustBoundary(client.app.state.authority).normalize(
                IngressEnvelope(
                    content="inspect",
                    source_type=SourceType.DIRECT_MESSAGE,
                    source_identity="owner-1",
                    authenticated=True,
                    conversation_id="cancel-test",
                )
            )
            pending = asyncio.create_task(service.start(event, "inspect"))
            await entered.wait()
            run = (await service.repository.list_runs())[0]
            cancelled = await service.cancel(run.run_id, actor_id="owner-1")
            assert cancelled.status == "cancelled"
            release.set()
            result = await pending
            assert result.status == "cancelled"
            assert not result.observations

        client.portal.call(exercise)
        assert not client.get("/v1/tasks", headers=OWNER).json()


def test_checkpoint_rejects_stale_writer(settings: Settings, tmp_path: Path) -> None:
    from living_agent.agent.repository import AgentConflictError

    with TestClient(create_app(configured(settings, tmp_path))) as client:
        run = start(client)

        async def exercise() -> None:
            repo = client.app.state.agent_service.repository
            old = await repo.get(run["run_id"])
            await repo.save(old)
            with pytest.raises(AgentConflictError):
                await repo.save(old)

        client.portal.call(exercise)


def test_chat_agent_controls_are_bound_to_origin_conversation(
    settings: Settings, tmp_path: Path
) -> None:
    with TestClient(create_app(configured(settings, tmp_path))) as client:
        run = start(client, "需要更多信息")
        reply = client.post(
            "/v1/chat",
            json={
                "content": f"查看智能体 {run['run_id']}",
                "source_type": "direct_message",
                "source_identity": "owner-1",
                "authenticated": True,
                "conversation_id": "different",
            },
        ).json()
        assert reply["agent_run_id"] is None
        assert "无法执行" in reply["message"]


def test_disabled_agent_and_untrusted_ingress_do_not_plan(
    settings: Settings, tmp_path: Path
) -> None:
    config = configured(settings, tmp_path).model_copy(update={"agent_enabled": False})
    with TestClient(create_app(config)) as client:
        assert (
            client.post("/v1/agent/runs", headers=OWNER, json={"goal": "inspect"}).status_code
            == 409
        )
    config = config.model_copy(update={"agent_enabled": True})
    with TestClient(create_app(config)) as client:
        for authenticated, source_type in [(False, "direct_message"), (True, "file")]:
            client.post(
                "/v1/chat",
                json={
                    "content": "agent: 检查工作区并读取 README",
                    "source_type": source_type,
                    "source_identity": "owner-1",
                    "authenticated": authenticated,
                    "conversation_id": "untrusted",
                },
            )
        assert not client.get("/v1/agent/runs", headers=OWNER).json()


def test_openai_compatible_agent_protocol_with_http_transport(
    settings: Settings, tmp_path: Path
) -> None:
    import httpx2
    from pydantic import SecretStr

    from living_agent.providers.llm import OpenAICompatibleLLMProvider

    calls: list[dict[str, Any]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["messages"][0]["role"] == "system"
        assert "final user-visible reply" not in payload["messages"][0]["content"]
        assert "structured JSON decision" in payload["messages"][0]["content"]
        sections = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
        observed = [
            json.loads(section["content"])
            if isinstance(section["content"], str)
            else section["content"]
            for section in sections
            if section["kind"] == "UNTRUSTED_TOOL_RESULT"
        ]
        decision = finish(observed) if observed else tool("workspace_read", path="README.md")
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(decision)},
                        "finish_reason": "stop",
                    }
                ],
                "model": "test-model",
                "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
            },
        )

    provider = OpenAICompatibleLLMProvider(
        base_url="https://model.example/v1",
        api_key=SecretStr("test-only"),
        model="test-model",
        timeout_seconds=2,
        max_attempts=1,
        retry_base_seconds=0,
        retry_max_seconds=0,
        max_output_tokens=1024,
        temperature=0,
        max_context_chars=100000,
        max_response_bytes=100000,
        client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        assert run["status"] == "completed", run
        assert len(calls) == 2
        audit = client.get("/v1/audit?limit=100", headers=OWNER).json()
        model_calls = [item for item in audit if item["action"] == "agent.model_called"]
        assert len(model_calls) == 2
        assert all(item["details"]["usage"]["total_tokens"] == 130 for item in model_calls)


def test_cancelled_child_stops_parent_instead_of_replanning(
    settings: Settings, tmp_path: Path
) -> None:
    provider = ScriptedProvider(
        lambda obs: tool("workspace_write", path="cancelled.txt", content="no")
    )
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        run = start(client)
        child_id = run["pending_proposal"]["task"]["task_id"]
        assert client.post(f"/v1/tasks/{child_id}/cancel", headers=OWNER).status_code == 200
        result = client.post(
            f"/v1/agent/runs/{run['run_id']}/resume", headers=OWNER, json={}
        ).json()
        assert result["status"] == "cancelled"
        assert result["iterations"] == 1
        assert len(client.get("/v1/tasks", headers=OWNER).json()) == 1
