"""Audited memory candidate and management workflows."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.memory.embeddings import MemoryEmbeddingIndex
from living_agent.memory.extractor import MemoryCandidateExtractor
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.recall import MemoryRecallService
from living_agent.memory.repository import MemoryRepository, MemoryVersionConflictError
from living_agent.memory.self_candidates import SelfMemoryCandidateGenerator
from living_agent.models.events import AuthorityLevel, TrustedEvent
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryCommitResult,
    MemoryEmbeddingStatus,
    MemoryFirewallDecision,
    MemoryMergeRequest,
    MemoryNode,
    MemoryReindexResult,
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
        embedding_index: MemoryEmbeddingIndex,
        extractor: MemoryCandidateExtractor,
        self_candidate_generator: SelfMemoryCandidateGenerator,
        auto_approval_enabled: bool,
        recall_candidate_limit: int,
        audit: AuditService,
    ) -> None:
        self._repository = repository
        self._events = events
        self._firewall = firewall
        self._recall = recall
        self._embedding_index = embedding_index
        self._extractor = extractor
        self._self_candidate_generator = self_candidate_generator
        self._auto_approval_enabled = auto_approval_enabled
        self._recall_candidate_limit = recall_candidate_limit
        self._audit = audit

    async def initialize(self) -> MemoryReindexResult:
        return await self._embedding_index.initialize()

    async def observe(self, event: TrustedEvent) -> MemoryCandidate | None:
        observed: list[MemoryCandidate] = []
        for candidate in self._extractor.extract_all(event):
            if await self._repository.candidate_exists(candidate.candidate_id):
                observed.append(await self._repository.get_candidate(candidate.candidate_id))
                continue
            created = await self.create_candidate(
                candidate,
                proposer_id=event.source_identity or "anonymous",
            )
            await self._audit.append(
                action="memory.candidate_extracted",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="pending",
                details={
                    "candidate_id": created.candidate_id,
                    "source_event_ids": created.source_event_ids,
                    "scope": created.scope,
                },
            )
            observed.append(
                await self._auto_approve(created) if self._auto_approval_enabled else created
            )
        return observed[0] if observed else None

    async def consider_self_candidate(self, event: TrustedEvent) -> MemoryCandidate | None:
        """Create a self-originated candidate without entering automatic approval."""

        candidate = self._self_candidate_generator.generate(event)
        if candidate is None:
            return None
        if await self._repository.candidate_exists(candidate.candidate_id):
            return await self._repository.get_candidate(candidate.candidate_id)
        created = await self.create_candidate(candidate, proposer_id="living-agent")
        await self._audit.append(
            action="memory.self_candidate_created",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome="pending",
            details={
                "candidate_id": created.candidate_id,
                "source_event_ids": created.source_event_ids,
                "scope": created.scope,
            },
        )
        return created

    async def _auto_approve(self, candidate: MemoryCandidate) -> MemoryCandidate:
        equivalent = await self._repository.equivalent_memory(candidate)
        if equivalent is not None:
            duplicate = await self._repository.reject_candidate(
                candidate.candidate_id,
                reason="equivalent_memory_exists",
            )
            await self._audit.append(
                action="memory.auto_approval",
                actor_id="living-agent",
                outcome="skipped",
                details={
                    "candidate_id": candidate.candidate_id,
                    "memory_id": equivalent.id,
                    "reason_code": "equivalent_memory_exists",
                    "source_event_ids": candidate.source_event_ids,
                    "scope": candidate.scope,
                },
            )
            return duplicate
        if await self._repository.has_conflict(candidate):
            deferred = await self._repository.defer_candidate(
                candidate.candidate_id,
                reason="conflicting_memory_requires_review",
            )
            await self._audit.append(
                action="memory.auto_approval",
                actor_id="living-agent",
                outcome="pending_review",
                details={
                    "candidate_id": candidate.candidate_id,
                    "memory_id": None,
                    "reason_code": "conflicting_memory_requires_review",
                    "source_event_ids": candidate.source_event_ids,
                    "scope": candidate.scope,
                },
            )
            return deferred
        result = await self.commit_candidate(
            candidate.candidate_id,
            actor_id="living-agent",
        )
        await self._audit.append(
            action="memory.auto_approval",
            actor_id="living-agent",
            outcome="committed" if result.memory is not None else "rejected",
            details={
                "candidate_id": candidate.candidate_id,
                "memory_id": result.memory.id if result.memory is not None else None,
                "reason_code": result.decision.reason_code,
                "source_event_ids": candidate.source_event_ids,
                "scope": candidate.scope,
            },
        )
        return result.candidate

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
        replace_conflicts: bool = False,
    ) -> MemoryCommitResult:
        candidate = await self._repository.get_candidate(candidate_id)
        if candidate.status is not CandidateStatus.PENDING:
            decision = MemoryFirewallDecision(allowed=False, reason_code="candidate_not_pending")
            return MemoryCommitResult(candidate=candidate, decision=decision)
        source_events = await self._events.get_many(candidate.source_event_ids)
        conflicts = await self._repository.conflicts(candidate)
        decision = self._firewall.evaluate(
            candidate,
            source_events=source_events,
            conflict_exists=bool(conflicts) and not replace_conflicts,
        )
        if not decision.allowed or decision.effective_factuality is None:
            if decision.reason_code == "conflicting_memory_requires_review":
                pending = await self._repository.defer_candidate(
                    candidate_id,
                    reason=decision.reason_code,
                )
                await self._audit.append(
                    action="memory.review_required",
                    actor_id=actor_id,
                    outcome="pending",
                    details={
                        "candidate_id": candidate_id,
                        "reason_code": decision.reason_code,
                        "conflicting_memory_ids": [memory.id for memory in conflicts],
                        "source_event_ids": candidate.source_event_ids,
                    },
                )
                return MemoryCommitResult(candidate=pending, decision=decision)
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
            supersede_memory_ids=(
                [memory.id for memory in conflicts] if replace_conflicts else []
            ),
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
        await self._synchronize_embedding(memory)
        if replace_conflicts:
            for conflict in conflicts:
                await self._remove_embedding(conflict.id)
            if conflicts:
                await self._audit.append(
                    action="memory.superseded",
                    actor_id=actor_id,
                    outcome="success",
                    details={
                        "candidate_id": candidate_id,
                        "memory_id": memory.id,
                        "superseded_memory_ids": [item.id for item in conflicts],
                    },
                )
        return MemoryCommitResult(
            candidate=committed_candidate,
            decision=decision,
            memory=memory,
        )

    async def reject_candidate(
        self,
        candidate_id: str,
        *,
        actor_id: str,
    ) -> MemoryCandidate:
        candidate = await self._repository.get_candidate(candidate_id)
        if candidate.status is not CandidateStatus.PENDING:
            raise MemoryVersionConflictError("memory candidate is no longer pending")
        rejected = await self._repository.reject_candidate(
            candidate_id,
            reason="owner_rejected",
        )
        await self._audit.append(
            action="memory.rejected",
            actor_id=actor_id,
            conversation_id=(
                candidate.scope.removeprefix("conversation:")
                if candidate.scope.startswith("conversation:")
                else None
            ),
            outcome="rejected",
            details={
                "candidate_id": candidate_id,
                "reason_code": "owner_rejected",
                "source_event_ids": candidate.source_event_ids,
            },
        )
        return rejected

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
        source_event_ids: list[str] | None = None,
        taint_labels: set[str] | None = None,
    ) -> list[MemoryNode]:
        accessible = await self._repository.search(
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=False,
            query="",
            include_deleted=False,
            limit=self._recall_candidate_limit,
        )
        semantic_scores = await self._embedding_index.semantic_scores(
            query,
            accessible,
            source_event_ids=source_event_ids or [],
            taint_labels=taint_labels or set(),
        )
        recalled = self._recall.rank(
            query,
            accessible,
            limit=limit,
            semantic_scores=semantic_scores,
        )
        await self._audit.append(
            action="memory.recalled",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="success",
            details={
                "requester_id": actor_id,
                "query_chars": len(query),
                "candidate_count": len(accessible),
                "semantic_candidate_count": len(semantic_scores),
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
        await self._synchronize_embedding(memory)
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
        if status is MemoryStatus.DELETED:
            await self._remove_embedding(memory.id)
        else:
            await self._synchronize_embedding(memory)
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
        for source_id in request.memory_ids:
            await self._remove_embedding(source_id)
        await self._synchronize_embedding(memory)
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
        await self._remove_embedding(memory_id)
        for memory in memories:
            await self._synchronize_embedding(memory)
        return memories

    async def embedding_status(self) -> MemoryEmbeddingStatus:
        return await self._embedding_index.status()

    async def reindex_embeddings(self, *, actor_id: str) -> MemoryReindexResult:
        return await self._embedding_index.reindex(actor_id=actor_id)

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

    async def _synchronize_embedding(self, memory: MemoryNode) -> None:
        try:
            await self._embedding_index.synchronize(memory)
        except Exception as exc:
            await self._audit_embedding_storage_failure(
                memory_id=memory.id,
                operation="synchronize",
                exc=exc,
            )

    async def _remove_embedding(self, memory_id: str) -> None:
        try:
            await self._embedding_index.remove(memory_id)
        except Exception as exc:
            await self._audit_embedding_storage_failure(
                memory_id=memory_id,
                operation="remove",
                exc=exc,
            )

    async def _audit_embedding_storage_failure(
        self,
        *,
        memory_id: str,
        operation: str,
        exc: Exception,
    ) -> None:
        await self._audit.append(
            action="memory.embedding_storage_failed",
            actor_id="living-agent",
            outcome="failure",
            details={
                "memory_id": memory_id,
                "operation": operation,
                "error_code": type(exc).__name__,
            },
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
