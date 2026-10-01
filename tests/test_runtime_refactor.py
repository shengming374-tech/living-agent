"""Exercise the handoff from verified execution into user-visible social speech."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.models.events import IngressEnvelope, SourceType
from living_agent.providers.llm import LLMProviderError, MockLLMProvider, ModelResponse

OWNER = {"X-Actor-ID": "owner-1"}
PLANNER_MARKER = "EXECUTIVE_RAW_SUMMARY_MARKER"


class SocialOutcomeProvider(MockLLMProvider):
    def __init__(self, *, reply: str = "看过啦, README 里是本地验收项目", fail: bool = False):
        super().__init__()
        self.reply = reply
        self.fail = fail
        self.social_contexts: list[CompiledContext] = []

    async def generate(self, context: CompiledContext) -> ModelResponse:
        current = next(
            (json.loads(section.content) for section in context.sections
             if section.kind is ContextKind.CURRENT_TASK), {},
        )
        if current.get("agent_protocol") == 1:
            response = await super().generate(context)
            decision = json.loads(response.text)
            if decision["action"] == "finish":
                decision["summary"] = PLANNER_MARKER
                response = response.model_copy(update={"text": json.dumps(decision)})
            return response
        if current.get("run_id"):
            self.social_contexts.append(context)
            if self.fail:
                raise LLMProviderError("model_unavailable", provider="scripted", model="social")
            return ModelResponse(text=self.reply, provider="scripted", model="social")
        return await super().generate(context)


def configured(settings: Settings, tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Runtime acceptance\nA local verified file.\n")
    return settings.model_copy(update={"work_workspace_root": workspace})


def chat(client: TestClient) -> dict:
    response = client.post("/v1/chat", json={
        "content": "agent: 检查工作区并读取 README",
        "source_type": "direct_message", "source_identity": "owner-1",
        "conversation_id": "social-agent-result", "authenticated": True,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_agent_outcome_uses_persona_and_source_separated_verified_results(
    settings: Settings, tmp_path: Path,
) -> None:
    provider = SocialOutcomeProvider(reply="我完成了 README 读取, 这是本地验收项目")
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        result = chat(client)
        audit = client.get("/v1/audit?limit=200", headers=OWNER).json()
    assert result["agent_run_id"]
    assert result["message"] == provider.reply
    assert PLANNER_MARKER not in " ".join(result["messages"])
    assert len(provider.social_contexts) == 1
    context = provider.social_contexts[0]
    root = next(section for section in context.sections if section.kind is ContextKind.ROOT_POLICY)
    assert "TRUSTED_PERSONA_PROFILE" in root.content
    assert "SOCIAL_RESPONSE_POLICY" in root.content
    assert PLANNER_MARKER not in root.content
    results = [section for section in context.sections
               if section.kind is ContextKind.UNTRUSTED_TOOL_RESULT]
    assert any("Runtime acceptance" in section.content for section in results)
    summary = next(section for section in results if PLANNER_MARKER in section.content)
    assert "model_output" in summary.taint_labels
    assert any(entry["details"].get("phase") == "agent_result_synthesis" for entry in audit
               if entry["action"] == "model.called")


def test_agent_social_failure_falls_back_to_host_evidence(
    settings: Settings, tmp_path: Path,
) -> None:
    provider = SocialOutcomeProvider(fail=True)
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        result = chat(client)
        audit = client.get("/v1/audit?limit=200", headers=OWNER).json()
    assert "README.md" in " ".join(result["messages"])
    assert PLANNER_MARKER not in " ".join(result["messages"])
    assert any(entry["outcome"] == "failure"
               and entry["details"].get("phase") == "agent_result_synthesis"
               for entry in audit if entry["action"] == "model.called")


def test_agent_social_output_cannot_invent_prior_memories(
    settings: Settings, tmp_path: Path,
) -> None:
    provider = SocialOutcomeProvider(reply="我记得你去年告诉过我这份文件")
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        result = chat(client)
        audit = client.get("/v1/audit?limit=200", headers=OWNER).json()
    assert result["message"] == "我没有足够的记录支持那样说"
    assert any(entry["details"].get("phase") == "agent_result_synthesis"
               for entry in audit if entry["action"] == "continuity.blocked")


async def test_agent_outcome_is_discarded_after_platform_turn_is_superseded(
    settings: Settings, tmp_path: Path,
) -> None:
    class SupersedingProvider(SocialOutcomeProvider):
        runtime = None

        async def generate(self, context: CompiledContext) -> ModelResponse:
            response = await super().generate(context)
            if self.social_contexts:
                assert self.runtime is not None
                await self.runtime.begin_utterance_turn("social-agent-result", platform="test")
            return response

    provider = SupersedingProvider()
    with TestClient(create_app(configured(settings, tmp_path), llm_provider=provider)) as client:
        provider.runtime = client.app.state.runtime
        result, turn = await provider.runtime.handle_platform_chat(
            IngressEnvelope(
                content="agent: 检查工作区并读取 README", source_type=SourceType.DIRECT_MESSAGE,
                source_identity="owner-1", conversation_id="social-agent-result",
                authenticated=True,
            ), platform="test",
        )
    assert turn is not None
    assert result.agent_run_id
    assert result.message is None
    assert result.messages == []
    assert result.utterance is None


def test_agent_simulation_previews_routing_without_executing(
    settings: Settings, tmp_path: Path,
) -> None:
    class NeverCalledProvider:
        async def generate(self, context: CompiledContext) -> ModelResponse:
            raise AssertionError("simulation must never call a model")

    app = create_app(configured(settings, tmp_path), llm_provider=NeverCalledProvider())
    with TestClient(app) as client:
        before = client.get("/v1/audit?limit=200", headers=OWNER).json()
        preview = client.post("/v1/simulator/turn", headers=OWNER, json={
            "content": "agent: 检查工作区并读取 README",
            "source_type": "direct_message", "source_identity": "owner-1",
            "conversation_id": "preview-agent", "authenticated": True,
        }).json()
        after = client.get("/v1/audit?limit=200", headers=OWNER).json()
        assert client.get("/v1/agent/runs", headers=OWNER).json() == []
        assert client.get("/v1/tasks", headers=OWNER).json() == []
    assert before == after
    assert preview["task_goal"] == "检查工作区并读取 README"
    assert preview["turn"]["mode"] == "act"
    assert preview["would_execute_tools"] is True
    assert preview["would_call_model"] is True
    assert "CURRENT_TASK" in preview["context_sections"]
    assert preview["task_steps"] == []
    assert preview["persisted"] is False
    assert preview["effects_executed"] is False


def test_short_agent_goal_keeps_exact_confirmation_command(
    settings: Settings, tmp_path: Path,
) -> None:
    class WriteProvider(SocialOutcomeProvider):
        async def generate(self, context: CompiledContext) -> ModelResponse:
            return ModelResponse(text=json.dumps({
                "action": "tool", "summary": "写入目标文件", "tool": "workspace_write",
                "arguments": {"path": "note.md", "content": "confirmed content"},
            }), provider="scripted")

    config = configured(settings, tmp_path)
    with TestClient(create_app(config, llm_provider=WriteProvider())) as client:
        result = client.post("/v1/chat", json={
            "content": "agent: 写 note", "source_type": "direct_message",
            "source_identity": "owner-1", "conversation_id": "short-agent",
            "authenticated": True,
        }).json()
        run = client.get(f"/v1/agent/runs/{result['agent_run_id']}", headers=OWNER).json()
    assert run["status"] == "waiting_confirmation"
    assert f"确认智能体 {run['run_id']}" in " ".join(result["messages"])
    assert not (config.work_workspace_root / "note.md").exists()
