"""Agent-authored, owner-approved managed-artifact change proposals."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.life.repository import LifeRepository, LifeStateError
from living_agent.management.artifacts import (
    ArtifactConflictError,
    StageRequest,
)
from living_agent.models.life import (
    SelfChangeProposal,
    SelfChangeProposalCreate,
    SelfChangeProposalStatus,
    SelfChangeTargetKind,
)
from living_agent.persona.manager import PersonaManager
from living_agent.prompts.manager import PromptManager


class SelfChangeService:
    def __init__(
        self,
        *,
        repository: LifeRepository,
        persona: PersonaManager,
        prompts: PromptManager,
        audit: AuditService,
    ) -> None:
        self._repository = repository
        self._persona = persona
        self._prompts = prompts
        self._audit = audit

    async def submit(self, create: SelfChangeProposalCreate) -> SelfChangeProposal:
        if (
            create.target_kind is SelfChangeTargetKind.PROMPT
            and create.target_path == "host/root.txt"
        ):
            raise LifeStateError("root prompt changes require the dedicated owner workflow")
        await self._repository.require_diary_ids(create.source_diary_ids)
        await self._repository.require_dream_ids(create.source_dream_ids)
        manager = self._manager(create.target_kind)
        current = await manager.view(create.target_path)
        if current.version != create.expected_version:
            raise ArtifactConflictError("self-change proposal base version is stale")
        stage = await manager.stage(
            create.target_path,
            StageRequest(
                content=create.proposed_content,
                expected_version=create.expected_version,
            ),
            actor_id="living-agent",
        )
        tested = await manager.test(stage.stage_id, actor_id="living-agent")
        proposal_status = (
            SelfChangeProposalStatus.READY
            if tested.tested
            else SelfChangeProposalStatus.TEST_FAILED
        )
        proposal = await self._repository.create_proposal(
            create,
            stage_id=tested.stage_id,
            diff=tested.diff,
            test_results=tested.test_results,
            status=proposal_status,
        )
        await self._audit.append(
            action="self_change.proposed",
            actor_id="living-agent",
            outcome=proposal.status.value,
            details={
                "proposal_id": proposal.proposal_id,
                "target_kind": proposal.target_kind.value,
                "target_path": proposal.target_path,
                "stage_id": proposal.stage_id,
                "source_diary_ids": proposal.source_diary_ids,
                "source_dream_ids": proposal.source_dream_ids,
            },
        )
        return proposal

    async def approve(
        self,
        proposal_id: str,
        *,
        actor_id: str,
    ) -> SelfChangeProposal:
        if actor_id == "living-agent":
            raise PermissionError("the agent cannot approve its own change proposal")
        proposal = await self._repository.get_proposal(proposal_id)
        if proposal.status is not SelfChangeProposalStatus.READY:
            raise LifeStateError("only a tested ready proposal can be approved")
        manager = self._manager(proposal.target_kind)
        try:
            deployed = await manager.deploy(proposal.stage_id, actor_id=actor_id)
        except ArtifactConflictError:
            await self._repository.set_proposal_status(
                proposal_id,
                status=SelfChangeProposalStatus.SUPERSEDED,
            )
            raise
        updated = await self._repository.set_proposal_status(
            proposal_id,
            status=SelfChangeProposalStatus.DEPLOYED,
            approved_by=actor_id,
            deployed_version=deployed.artifact.version,
        )
        await self._audit.append(
            action="self_change.approved",
            actor_id=actor_id,
            outcome="deployed",
            details={
                "proposal_id": proposal_id,
                "target_kind": proposal.target_kind.value,
                "target_path": proposal.target_path,
                "deployed_version": deployed.artifact.version,
                "restart_required": deployed.restart_required,
            },
        )
        return updated

    async def reject(
        self,
        proposal_id: str,
        *,
        actor_id: str,
    ) -> SelfChangeProposal:
        if actor_id == "living-agent":
            raise PermissionError("the agent cannot reject its own change proposal")
        proposal = await self._repository.get_proposal(proposal_id)
        if proposal.status not in {
            SelfChangeProposalStatus.READY,
            SelfChangeProposalStatus.TEST_FAILED,
        }:
            raise LifeStateError("self-change proposal is already terminal")
        rejected = await self._repository.set_proposal_status(
            proposal_id,
            status=SelfChangeProposalStatus.REJECTED,
            approved_by=actor_id,
        )
        await self._audit.append(
            action="self_change.rejected",
            actor_id=actor_id,
            outcome="rejected",
            details={"proposal_id": proposal_id},
        )
        return rejected

    async def get(self, proposal_id: str) -> SelfChangeProposal:
        return await self._repository.get_proposal(proposal_id)

    async def proposals(self, *, limit: int = 100) -> list[SelfChangeProposal]:
        return await self._repository.proposals(limit=limit)

    def _manager(self, kind: SelfChangeTargetKind) -> PersonaManager | PromptManager:
        if kind is SelfChangeTargetKind.PERSONA:
            return self._persona
        return self._prompts
