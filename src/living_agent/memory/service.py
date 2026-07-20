"""Audited memory candidate and management workflows."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.recall import MemoryRecallService
from living_agent.memory.repository import MemoryRepository
from living_agent.models.events import AuthorityLevel, TrustedEvent
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryCommitResult,
    MemoryFirewallDecision,
    MemoryMergeRequest,
    MemoryNode,
    MemorySplitRequest,
    MemoryStatus,
    MemoryUpdate,
    MemoryUsage,
    MemoryVersion,
)
from living_agent.storage.events import EventRepository


class MemoryAccessError(PermissionError):
    pass


class MemoryService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        events: EventRepository,
        firewall: MemoryFirewall,
        recall: MemoryRecallService,
        audit: AuditService,
    ) -> None:
        self._repository = repository
        self._events = events
        self._firewall = firewall
        self._recall = recall
        self._audit = audit

    async def create_candidate(
        self,
        candidate: MemoryCandidateCreate,
        *,
        proposer_id: str,
    ) -> MemoryCandidate:
        source_events = await self._events.get_many(candidate.source_event_ids)
        source_trust = self._least_source_trust(source_events)
        created = await self._repository.create_candidate(
            candidate,
            proposer_id=proposer_id,
            source_trust=source_trust,
        )
        await self._audit.append(
            action="memory.candidate_created",
            actor_id=proposer_id,
            outcome="pending",
            details={
                "candidate_id": created.candidate_id,
                "source_event_ids": created.source_event_ids,
                "scope": created.scope,
                "factuality": created.factuality.value,
            },
        )
        return created

    async def commit_candidate(
        self,
        candidate_id: str,
        *,
        actor_id: str,
    ) -> MemoryCommitResult:
        candidate = await self._repository.get_candidate(candidate_id)
        if candidate.status is not CandidateStatus.PENDING:
            decision = MemoryFirewallDecision(allowed=False, reason_code="candidate_not_pending")
            return MemoryCommitResult(candidate=candidate, decision=decision)
        source_events = await self._events.get_many(candidate.source_event_ids)
        decision = self._firewall.evaluate(
            candidate,
            source_events=source_events,
            conflict_exists=await self._repository.has_conflict(candidate),
        )
        if not decision.allowed or decision.effective_factuality is None:
            rejected = await self._repository.reject_candidate(
                candidate_id,
                reason=decision.reason_code,
            )
            await self._audit.append(
                action="memory.rejected",
                actor_id=actor_id,
                outcome="rejected",
                details={
                    "candidate_id": candidate_id,
                    "reason_code": decision.reason_code,
                    "source_event_ids": candidate.source_event_ids,
                },
            )
            return MemoryCommitResult(candidate=rejected, decision=decision)
        committed_candidate, memory = await self._repository.commit_candidate(
            candidate_id,
            factuality=decision.effective_factuality,
            actor_id=actor_id,
        )
        await self._audit.append(
            action="memory.created",
            actor_id=actor_id,
            outcome="committed",
            details={
                "candidate_id": candidate_id,
                "memory_id": memory.id,
                "scope": memory.scope,
                "version": memory.version,
                "factuality": memory.factuality.value,
                "source_event_ids": memory.source_event_ids,
            },
        )
        return MemoryCommitResult(
            candidate=committed_candidate,
            decision=decision,
            memory=memory,
        )

    async def candidates(
        self,
        *,
        status: CandidateStatus | None,
        limit: int,
    ) -> list[MemoryCandidate]:
        return await self._repository.list_candidates(status=status, limit=limit)

    async def search(
        self,
        *,
        actor_id: str,
        conversation_id: str | None,
        owner: bool,
        query: str,
        include_deleted: bool,
        limit: int,
    ) -> list[MemoryNode]:
        return await self._repository.search(
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=owner,
            query=query,
            include_deleted=include_deleted and owner,
            limit=limit,
        )

    async def recall(
        self,
        *,
        actor_id: str,
        conversation_id: str | None,
        query: str,
        limit: int = 4,
    ) -> list[MemoryNode]:
        accessible = await self._repository.search(
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=False,
            query="",
            include_deleted=False,
            limit=100,
        )
        recalled = self._recall.rank(query, accessible, limit=limit)
        await self._audit.append(
            action="memory.recalled",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="success",
            details={
                "requester_id": actor_id,
                "query_chars": len(query),
                "candidate_count": len(accessible),
                "recalled_memory_ids": [memory.id for memory in recalled],
            },
        )
        return recalled

    async def get_accessible(
        self,
        memory_id: str,
        *,
        actor_id: str,
        conversation_id: str | None,
        owner: bool,
    ) -> MemoryNode:
        memory = await self._repository.get(memory_id)
        if not self._can_access(
            memory,
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=owner,
        ):
            raise MemoryAccessError("memory scope denied")
        return memory

    async def update(
        self,
        memory_id: str,
        update: MemoryUpdate,
        *,
        actor_id: str,
    ) -> MemoryNode:
        memory = await self._repository.update(memory_id, update, actor_id=actor_id)
        await self._audit_change("memory.updated", memory, actor_id=actor_id)
        return memory

    async def change_status(
        self,
        memory_id: str,
        *,
        expected_version: int,
        status: MemoryStatus,
        actor_id: str,
    ) -> MemoryNode:
        memory = await self._repository.change_status(
            memory_id,
            expected_version=expected_version,
            status=status,
            actor_id=actor_id,
        )
        action = "memory.deleted" if status is MemoryStatus.DELETED else "memory.restored"
        await self._audit_change(action, memory, actor_id=actor_id)
        return memory

    async def versions(self, memory_id: str) -> list[MemoryVersion]:
        return await self._repository.versions(memory_id)

    async def usages(self, memory_id: str) -> list[MemoryUsage]:
        return await self._repository.usages(memory_id)

    async def sources(self, memory_id: str) -> list[TrustedEvent]:
        memory = await self._repository.get(memory_id)
        return await self._events.get_many(memory.source_event_ids)

    async def merge(
        self,
        request: MemoryMergeRequest,
        *,
        actor_id: str,
    ) -> MemoryNode:
        memory = await self._repository.merge(request, actor_id=actor_id)
        await self._audit.append(
            action="memory.merged",
            actor_id=actor_id,
            outcome="success",
            details={
                "memory_id": memory.id,
                "source_memory_ids": request.memory_ids,
                "version": memory.version,
            },
        )
        return memory

    async def split(
        self,
        memory_id: str,
        request: MemorySplitRequest,
        *,
        actor_id: str,
    ) -> list[MemoryNode]:
        memories = await self._repository.split(memory_id, request, actor_id=actor_id)
        await self._audit.append(
            action="memory.split",
            actor_id=actor_id,
            outcome="success",
            details={
                "source_memory_id": memory_id,
                "created_memory_ids": [memory.id for memory in memories],
            },
        )
        return memories

    async def record_usage(
        self,
        memory_id: str,
        *,
        response_id: str,
        conversation_id: str,
    ) -> MemoryUsage:
        usage = await self._repository.record_usage(
            memory_id,
            response_id=response_id,
            conversation_id=conversation_id,
        )
        await self._audit.append(
            action="memory.used",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="recorded",
            details={"memory_id": memory_id, "response_id": response_id},
        )
        return usage

    async def _audit_change(self, action: str, memory: MemoryNode, *, actor_id: str) -> None:
        await self._audit.append(
            action=action,
            actor_id=actor_id,
            outcome="success",
            details={"memory_id": memory.id, "version": memory.version},
        )

    @staticmethod
    def _can_access(
        memory: MemoryNode,
        *,
        actor_id: str,
        conversation_id: str | None,
        owner: bool,
    ) -> bool:
        if owner:
            return True
        return memory.scope in {
            "global",
            f"private:{actor_id}",
            f"conversation:{conversation_id}" if conversation_id else "",
        }

    @staticmethod
    def _least_source_trust(events: list[TrustedEvent]) -> str:
        if not events:
            return "untrusted"
        ranking = {"untrusted": 0, "authenticated": 1, "trusted": 2}
        return min((event.trust_level.value for event in events), key=ranking.__getitem__)


def is_owner(authority: AuthorityLevel) -> bool:
    return authority is AuthorityLevel.OWNER
