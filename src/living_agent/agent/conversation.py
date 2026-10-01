"""社交层与目标循环的交接。 / Handoff between conversation and persistent agency."""

import re

from living_agent.agent.contracts import AgentRun
from living_agent.agent.service import AgentService
from living_agent.models.events import AuthorityLevel, TrustedEvent

_AGENT_PREFIX = re.compile(r"^\s*(?:agent|智能体|自主任务)\s*[:：]\s*(.+)$", re.I | re.S)  # noqa: RUF001
_AGENT_CONTROL = re.compile(
    r"^\s*(确认|继续|取消|查看)\s*(?:agent|智能体)\s+([0-9a-f-]{36})"
    r"(?:\s+(.+))?\s*$",
    re.I | re.S,
)


class AgentConversation:
    def __init__(self, agent: AgentService) -> None:
        self.agent = agent

    async def handle(self, event: TrustedEvent, *, fallback: bool = False) -> AgentRun | None:
        if not self.agent.enabled or event.authority_level not in {
            AuthorityLevel.OWNER,
            AuthorityLevel.ADMIN,
        }:
            return None
        text = (
            event.content if isinstance(event.content, str) else str(event.content.get("text", ""))
        )
        command = _AGENT_CONTROL.fullmatch(text)
        if command:
            self.agent.authorize(event)
            operation, run_id, note = command.groups()
            run = await self.agent.repository.get(run_id)
            if run.event.conversation_id != event.conversation_id:
                raise PermissionError("agent belongs to another conversation")
            if run.event.source_identity != event.source_identity and (
                event.authority_level is not AuthorityLevel.OWNER
            ):
                raise PermissionError("agent belongs to another requester")
            actor = event.source_identity or "anonymous"
            if operation == "取消":
                return await self.agent.cancel(run_id, actor_id=actor)
            if operation in {"确认", "继续"}:
                return await self.agent.resume(
                    run_id, actor_id=actor, message=note, confirm=operation == "确认"
                )
            return run
        goal = self.preview_goal(event, fallback=fallback)
        if goal is not None:
            return await self.agent.start(event, goal)
        return None

    def preview_goal(self, event: TrustedEvent, *, fallback: bool = False) -> str | None:
        """Parse and authorize a goal without storing a run or invoking a model."""

        if not self.agent.enabled or event.authority_level not in {
            AuthorityLevel.OWNER, AuthorityLevel.ADMIN,
        }:
            return None
        text = (
            event.content if isinstance(event.content, str) else str(event.content.get("text", ""))
        )
        match = _AGENT_PREFIX.fullmatch(text)
        goal = match.group(1) if match else None
        if goal is None and fallback and text.strip().startswith(("帮我", "请帮我", "麻烦你")):
            goal = text[:1000]
        if goal is not None:
            self.agent.authorize(event)
        return goal
