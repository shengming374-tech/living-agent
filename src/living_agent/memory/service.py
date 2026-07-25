"""Audited memory candidate and management workflows."""

from __future__ import annotations

import asyncio
import hashlib
from uuid import uuid4

from living_agent.audit.service import AuditService
from living_agent.memory.embeddings import MemoryEmbeddingIndex
from living_agent.memory.extractor import MemoryCandidateExtractor
from living_agent.memory.facts import (
    RecallRoute,
    extract_fact,
    fact_response_match,
    forget_fact_key,
    route_recall,
)
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.recall import MemoryRecallService
from living_agent.memory.repository import MemoryRepository, MemoryVersionConflictError
from living_agent.memory.self_candidates import SelfMemoryCandidateGenerator
from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent, TrustLevel
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryCommitResult,
    MemoryEmbeddingStatus,
    MemoryFirewallDecision,
    MemoryLayer,
    MemoryMergeRequest,
    MemoryNode,
    MemoryRecallBatch,
    MemoryRecallTrace,
    MemoryRecallTraceBundle,
    MemoryRecallTraceCreate,
    MemoryRecallTraceItemCreate,
    MemoryReindexResult,
    MemorySplitRequest,
    MemoryStatus,
    MemorySupportMode,
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
        recall_mode: str,
        recall_min_score: float,
        narrative_recall_limit: int,
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
        self._recall_mode = recall_mode
        self._recall_min_score = recall_min_score
        self._narrative_recall_limit = narrative_recall_limit
        self._audit = audit
        self._candidate_application_lock = asyncio.Lock()

    async def initialize(self) -> MemoryReindexResult:
        await self._normalize_legacy_facts()
        await self._reject_legacy_interrogatives()
        return await self._embedding_index.initialize()

    async def observe(self, event: TrustedEvent) -> MemoryCandidate | None:
        if await self._apply_forget_command(event):
            return None
        observed: list[MemoryCandidate] = []
        for extracted in self._extractor.extract_all(event):
            candidate, explicit_correction = self._prepare_observed_candidate(
                event,
                extracted,
            )
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
                await self._auto_approve(
                    created,
                    explicit_correction=explicit_correction,
                )
                if self._auto_approval_enabled
                else created
            )
        return observed[0] if observed else None

    async def _apply_forget_command(self, event: TrustedEvent) -> bool:
        if (
            event.source_type is not SourceType.DIRECT_MESSAGE
            or event.trust_level is not TrustLevel.AUTHENTICATED
            or event.source_identity is None
        ):
            return False
        raw_content = (
            event.content
            if isinstance(event.content, str)
            else event.content.get("text", "")
        )
        if not isinstance(raw_content, str):
            return False
        memory_key = forget_fact_key(raw_content)
        if memory_key is None:
            return False
        memory = await self._repository.exact_fact(
            entity_id=event.source_identity,
            memory_key=memory_key,
            actor_id=event.source_identity,
            conversation_id=event.conversation_id,
            owner=False,
        )
        if memory is None:
            await self._audit.append(
                action="memory.forget_requested",
                actor_id=event.source_identity,
                conversation_id=event.conversation_id,
                outcome="not_found",
                details={
                    "event_id": event.event_id,
                    "memory_key": memory_key,
                },
            )
            return True
        forgotten = await self.change_status(
            memory.id,
            expected_version=memory.version,
            status=MemoryStatus.DELETED,
            actor_id=event.source_identity,
        )
        await self._audit.append(
            action="memory.forgotten",
            actor_id=event.source_identity,
            conversation_id=event.conversation_id,
            outcome="success",
            details={
                "event_id": event.event_id,
                "memory_id": forgotten.id,
                "memory_key": memory_key,
                "version": forgotten.version,
            },
        )
        return True

    @staticmethod
    def _prepare_observed_candidate(
        event: TrustedEvent,
        candidate: MemoryCandidateCreate,
    ) -> tuple[MemoryCandidateCreate, bool]:
        """Promote only authenticated direct self-reports into the exact fact ledger."""

        if (
            event.source_type in {
                SourceType.DIRECT_MESSAGE,
                SourceType.GROUP_MESSAGE,
            }
            and event.source_identity is not None
            and isinstance(candidate.content, str)
        ):
            fact = extract_fact(candidate.content)
            if fact is not None:
                return (
                    candidate.model_copy(
                        update={
                            "content": fact.content,
                            "memory_layer": MemoryLayer.FACT,
                            "entity_id": event.source_identity,
                            "memory_key": fact.key,
                        }
                    ),
                    fact.correction
                    if event.source_type is SourceType.DIRECT_MESSAGE
                    else False,
                )
        return (
            candidate.model_copy(update={"memory_layer": MemoryLayer.NARRATIVE}),
            False,
        )

    async def _normalize_legacy_facts(self) -> None:
        memories = await self._repository.search(
            actor_id="living-agent",
            conversation_id=None,
            owner=True,
            query="",
            include_deleted=True,
            limit=100_000,
        )
        for memory in memories:
            if memory.memory_layer is MemoryLayer.FACT or not isinstance(
                memory.content,
                str,
            ):
                continue
            fact = extract_fact(memory.content)
            if fact is None:
                continue
            events = await self._events.get_many(memory.source_event_ids)
            source = next(
                (
                    event
                    for event in events
                    if event.source_type is SourceType.DIRECT_MESSAGE
                    and event.source_identity is not None
                ),
                None,
            )
            if source is None:
                continue
            assert source.source_identity is not None
            migrated = await self._repository.normalize_fact(
                memory.id,
                structured_content=fact.content,
                entity_id=source.source_identity,
                memory_key=fact.key,
                actor_id="living-agent-migration",
            )
            await self._remove_embedding(migrated.id)
            await self._audit.append(
                action="memory.migrated",
                actor_id="living-agent",
                conversation_id=source.conversation_id,
                outcome="success",
                details={
                    "memory_id": migrated.id,
                    "memory_key": migrated.memory_key,
                    "version": migrated.version,
                    "source_event_ids": migrated.source_event_ids,
                },
            )

    async def _reject_legacy_interrogatives(self) -> None:
        candidates = await self._repository.list_candidates(
            status=CandidateStatus.PENDING,
            limit=100_000,
        )
        for candidate in candidates:
            content = candidate.content
            if not isinstance(content, str):
                continue
            routed = route_recall(content)
            if (
                routed.route is RecallRoute.NONE
                and not content.rstrip().endswith(("?", "\uFF1F"))
            ):
                continue
            rejected = await self._repository.reject_candidate(
                candidate.candidate_id,
                reason="interrogative_not_memory",
            )
            await self._audit.append(
                action="memory.candidate_migrated",
                actor_id="living-agent",
                outcome="rejected",
                details={
                    "candidate_id": rejected.candidate_id,
                    "reason_code": "interrogative_not_memory",
                    "source_event_ids": rejected.source_event_ids,
                },
            )

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

    async def _auto_approve(
        self,
        candidate: MemoryCandidate,
        *,
        explicit_correction: bool = False,
    ) -> MemoryCandidate:
        if candidate.memory_layer is MemoryLayer.FACT:
            if not candidate.scope.startswith("private:"):
                deferred = await self._repository.defer_candidate(
                    candidate.candidate_id,
                    reason="non_private_fact_requires_review",
                )
                await self._audit.append(
                    action="memory.auto_approval",
                    actor_id="living-agent",
                    outcome="pending_review",
                    details={
                        "candidate_id": candidate.candidate_id,
                        "memory_id": None,
                        "reason_code": "non_private_fact_requires_review",
                        "source_event_ids": candidate.source_event_ids,
                        "scope": candidate.scope,
                    },
                )
                return deferred
            applied = await self._repository.apply_existing_fact(
                candidate.candidate_id,
                actor_id="living-agent",
                correction=explicit_correction,
            )
            if applied is not None:
                committed, memory, change_type = applied
                await self._remove_embedding(memory.id)
                await self._audit.append(
                    action=f"memory.fact_{change_type}",
                    actor_id="living-agent",
                    outcome="committed",
                    details={
                        "candidate_id": committed.candidate_id,
                        "memory_id": memory.id,
                        "memory_key": memory.memory_key,
                        "version": memory.version,
                        "source_event_ids": committed.source_event_ids,
                    },
                )
                return committed
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
        if candidate.memory_layer is None:
            candidate = candidate.model_copy(
                update={"memory_layer": MemoryLayer.NARRATIVE}
            )
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

    async def apply_candidate(
        self,
        candidate_id: str,
        *,
        actor_id: str,
        replace_conflicts: bool = False,
    ) -> MemoryCommitResult:
        """Apply a pending candidate or safely replay a previously committed one."""

        async with self._candidate_application_lock:
            return await self._apply_candidate_locked(
                candidate_id,
                actor_id=actor_id,
                replace_conflicts=replace_conflicts,
            )

    async def _apply_candidate_locked(
        self,
        candidate_id: str,
        *,
        actor_id: str,
        replace_conflicts: bool,
    ) -> MemoryCommitResult:
        candidate = await self._repository.get_candidate(candidate_id)
        if candidate.status is CandidateStatus.PENDING:
            return await self.commit_candidate(
                candidate_id,
                actor_id=actor_id,
                replace_conflicts=replace_conflicts,
            )
        if candidate.status is CandidateStatus.REJECTED:
            decision = MemoryFirewallDecision(
                allowed=False,
                reason_code="candidate_rejected",
            )
            await self._audit_candidate_application(
                candidate,
                actor_id=actor_id,
                outcome="blocked",
                decision=decision,
            )
            return MemoryCommitResult(candidate=candidate, decision=decision)

        equivalent = await self._repository.equivalent_memory(candidate)
        if equivalent is not None:
            decision = MemoryFirewallDecision(
                allowed=True,
                reason_code="memory_already_active",
                effective_factuality=equivalent.factuality,
            )
            await self._audit_candidate_application(
                candidate,
                actor_id=actor_id,
                outcome="already_active",
                decision=decision,
                memory=equivalent,
            )
            return MemoryCommitResult(
                candidate=candidate,
                decision=decision,
                memory=equivalent,
            )

        replay = await self._repository.equivalent_pending_candidate(candidate)
        if replay is None:
            source_events = await self._events.get_many(candidate.source_event_ids)
            conflicts = await self._repository.conflicts(candidate)
            preflight = self._firewall.evaluate(
                candidate,
                source_events=source_events,
                conflict_exists=bool(conflicts) and not replace_conflicts,
            )
            if (
                not preflight.allowed
                and preflight.reason_code != "conflicting_memory_requires_review"
            ):
                await self._audit_candidate_application(
                    candidate,
                    actor_id=actor_id,
                    outcome="blocked",
                    decision=preflight,
                )
                return MemoryCommitResult(candidate=candidate, decision=preflight)
            replay = await self._repository.create_candidate(
                MemoryCandidateCreate(
                    type=candidate.type,
                    content=candidate.content,
                    subject=candidate.subject,
                    source_event_ids=candidate.source_event_ids,
                    factuality=candidate.factuality,
                    confidence=candidate.confidence,
                    importance=candidate.importance,
                    scope=candidate.scope,
                    memory_layer=candidate.memory_layer,
                    entity_id=candidate.entity_id,
                    memory_key=candidate.memory_key,
                    valid_until=candidate.valid_until,
                    superseded_by_id=candidate.superseded_by_id,
                ),
                proposer_id=candidate.proposer_id,
                source_trust=self._least_source_trust(source_events),
            )

        result = await self.commit_candidate(
            replay.candidate_id,
            actor_id=actor_id,
            replace_conflicts=replace_conflicts,
        )
        outcome = (
            "committed"
            if result.memory is not None
            else "pending_review"
            if result.candidate.status is CandidateStatus.PENDING
            else "blocked"
        )
        await self._audit_candidate_application(
            candidate,
            actor_id=actor_id,
            outcome=outcome,
            decision=result.decision,
            replay_candidate=result.candidate,
            memory=result.memory,
        )
        return result

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
        batch = await self.recall_with_trace(
            actor_id=actor_id,
            conversation_id=conversation_id,
            event_id=(
                source_event_ids[0]
                if source_event_ids
                else hashlib.sha256(query.encode("utf-8")).hexdigest()[:36]
            ),
            query=query,
            limit=limit,
            source_event_ids=source_event_ids,
            taint_labels=taint_labels,
        )
        return batch.memories

    async def recall_with_trace(
        self,
        *,
        actor_id: str,
        conversation_id: str | None,
        event_id: str,
        query: str,
        limit: int = 4,
        source_event_ids: list[str] | None = None,
        taint_labels: set[str] | None = None,
    ) -> MemoryRecallBatch:
        routed = route_recall(query)
        accessible = await self._repository.search(
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=False,
            query="",
            include_deleted=False,
            limit=self._recall_candidate_limit,
        )
        current_sources = set(source_event_ids or [])
        accessible = [
            memory
            for memory in accessible
            if not current_sources.intersection(memory.source_event_ids)
        ]
        selected, item_specs, semantic_count = await self._select_for_route(
            actor_id=actor_id,
            conversation_id=conversation_id,
            query=query,
            routed_route=routed.route,
            fact_key=routed.fact_key,
            accessible=accessible,
            limit=limit,
            source_event_ids=source_event_ids or [],
            taint_labels=taint_labels or set(),
        )
        route_name = routed.route.value
        if self._recall_mode == "legacy":
            route_name = "legacy"
        elif self._recall_mode == "shadow":
            route_name = f"shadow:{route_name}"
        trace_create = MemoryRecallTraceCreate(
            event_id=event_id,
            conversation_id=conversation_id or f"private:{actor_id}",
            actor_id=actor_id,
            route=route_name,
            query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
        )
        items = [
            MemoryRecallTraceItemCreate(
                trace_id=trace_create.trace_id,
                memory_id=memory.id,
                memory_layer=memory.memory_layer or MemoryLayer.LEGACY,
                selection_reason=reason,
                lexical_score=lexical_score,
                semantic_score=semantic_score,
                final_score=final_score,
                selected=True,
                injected=False,
                source_overlap=False,
            )
            for memory, reason, lexical_score, semantic_score, final_score in item_specs
        ]
        trace = await self._repository.create_recall_trace(trace_create, items=items)
        await self._audit.append(
            action="memory.recall_routed",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome=route_name,
            details={
                "trace_id": trace.trace.trace_id,
                "event_id": event_id,
                "requester_id": actor_id,
                "reason_code": routed.reason_code,
            },
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
                "semantic_candidate_count": semantic_count,
                "recalled_memory_ids": [memory.id for memory in selected],
                "trace_id": trace.trace.trace_id,
                "route": route_name,
            },
        )
        return MemoryRecallBatch(
            memories=selected,
            trace_id=trace.trace.trace_id,
            route=route_name,
        )

    async def _select_for_route(
        self,
        *,
        actor_id: str,
        conversation_id: str | None,
        query: str,
        routed_route: RecallRoute,
        fact_key: str | None,
        accessible: list[MemoryNode],
        limit: int,
        source_event_ids: list[str],
        taint_labels: set[str],
    ) -> tuple[
        list[MemoryNode],
        list[tuple[MemoryNode, str, float | None, float | None, float | None]],
        int,
    ]:
        narrative_limit = min(limit, self._narrative_recall_limit)

        async def ranked_narratives(
            candidates: list[MemoryNode],
            *,
            reason: str,
            min_score: float,
            ranked_limit: int,
            context_bonus: float = 0.0,
        ) -> tuple[
            list[MemoryNode],
            list[tuple[MemoryNode, str, float | None, float | None, float | None]],
            int,
        ]:
            semantic_scores = await self._embedding_index.semantic_scores(
                query,
                candidates,
                source_event_ids=source_event_ids,
                taint_labels=taint_labels,
            )
            ranked = self._recall.rank_with_scores(
                query,
                candidates,
                limit=ranked_limit,
                semantic_scores=semantic_scores,
                min_score=min_score,
                context_bonus=context_bonus,
            )
            return (
                [item.memory for item in ranked],
                [
                    (
                        item.memory,
                        reason,
                        item.lexical_score,
                        item.semantic_score,
                        item.final_score,
                    )
                    for item in ranked
                ],
                len(semantic_scores),
            )

        legacy_candidates = [
            memory
            for memory in accessible
            if memory.memory_layer is not MemoryLayer.FACT
        ]
        if self._recall_mode in {"legacy", "shadow"}:
            return await ranked_narratives(
                legacy_candidates,
                reason=(
                    "legacy_recall"
                    if self._recall_mode == "legacy"
                    else "shadow_legacy_injection"
                ),
                min_score=0.0,
                ranked_limit=limit,
            )

        if routed_route is RecallRoute.NONE:
            return [], [], 0

        if routed_route is RecallRoute.EXACT_FACT and fact_key is not None:
            fact = await self._repository.exact_fact(
                entity_id=actor_id,
                memory_key=fact_key,
                actor_id=actor_id,
                conversation_id=conversation_id,
                owner=False,
            )
            if fact is not None:
                return [fact], [(fact, "exact_fact_key", 1.0, None, 1.0)], 0
            return await ranked_narratives(
                legacy_candidates,
                reason="legacy_exact_fact_fallback",
                min_score=self._recall_min_score,
                ranked_limit=1,
            )

        if routed_route is RecallRoute.FACT_SET and fact_key is not None:
            prefix = f"{fact_key}."
            facts = [
                memory
                for memory in accessible
                if memory.memory_layer is MemoryLayer.FACT
                and memory.entity_id == actor_id
                and memory.memory_key is not None
                and (
                    memory.memory_key == fact_key
                    or memory.memory_key.startswith(prefix)
                )
            ][:limit]
            if facts:
                return (
                    facts,
                    [(fact, "exact_fact_set", 1.0, None, 1.0) for fact in facts],
                    0,
                )
            return await ranked_narratives(
                legacy_candidates,
                reason="legacy_fact_set_fallback",
                min_score=self._recall_min_score,
                ranked_limit=narrative_limit,
            )

        typed = legacy_candidates
        return await ranked_narratives(
            typed,
            reason=f"{routed_route.value}_ranked",
            min_score=self._recall_min_score,
            ranked_limit=narrative_limit,
            context_bonus=0.15,
        )

    async def mark_trace_injected(
        self,
        trace_id: str,
        *,
        memory_ids: list[str],
        context_fingerprint: str,
    ) -> MemoryRecallTraceBundle:
        selected = set(memory_ids)
        bundle = await self._repository.get_recall_trace(trace_id)
        item_updates: dict[str, dict[str, bool | None]] = {
            item.memory_id: {"injected": item.memory_id in selected}
            for item in bundle.items
        }
        support_mode = (
            MemorySupportMode.PENDING
            if selected
            else MemorySupportMode.NOT_INJECTED
        )
        updated = await self._repository.complete_recall_trace(
            trace_id,
            context_fingerprint=context_fingerprint,
            support_mode=support_mode,
            item_updates=item_updates,
        )
        await self._audit.append(
            action="memory.injected",
            actor_id="living-agent",
            conversation_id=updated.trace.conversation_id,
            outcome="injected" if selected else "not_injected",
            details={
                "trace_id": trace_id,
                "memory_ids": sorted(selected),
                "route": updated.trace.route,
            },
        )
        return updated

    async def mark_response_supported(
        self,
        trace_id: str,
        *,
        response_text: str,
        corroborating_text: str,
    ) -> MemoryRecallTraceBundle:
        bundle = await self._repository.get_recall_trace(trace_id)
        item_updates: dict[str, dict[str, bool | None]] = {}
        matched_facts: list[tuple[str, bool]] = []
        injected_count = 0
        for item in bundle.items:
            if not item.injected:
                continue
            injected_count += 1
            memory = await self._repository.get(item.memory_id)
            if (
                memory.memory_layer is MemoryLayer.FACT
                and isinstance(memory.content, dict)
                and isinstance(memory.content.get("value"), str)
            ):
                value = str(memory.content["value"])
                response_match = fact_response_match(value, response_text)
                source_overlap = fact_response_match(value, corroborating_text)
                matched_facts.append((memory.id, source_overlap))
            else:
                response_match = None
                source_overlap = False
            item_updates[memory.id] = {
                "injected": True,
                "response_match": response_match,
                "source_overlap": source_overlap,
            }

        fact_matches = [
            (memory_id, source_overlap)
            for memory_id, source_overlap in matched_facts
            if item_updates[memory_id]["response_match"] is True
        ]
        if injected_count == 0:
            support_mode = MemorySupportMode.NOT_INJECTED
        elif fact_matches:
            support_mode = (
                MemorySupportMode.CORROBORATED
                if any(source_overlap for _memory_id, source_overlap in fact_matches)
                else MemorySupportMode.MEMORY_ONLY
            )
        else:
            support_mode = MemorySupportMode.INJECTED_UNVERIFIED

        updated = await self._repository.complete_recall_trace(
            trace_id,
            support_mode=support_mode,
            item_updates=item_updates,
        )
        await self._audit.append(
            action="memory.response_supported",
            actor_id="living-agent",
            conversation_id=updated.trace.conversation_id,
            outcome=support_mode.value,
            details={
                "trace_id": trace_id,
                "route": updated.trace.route,
                "matched_memory_ids": [
                    memory_id for memory_id, _source_overlap in fact_matches
                ],
                "injected_count": injected_count,
            },
        )
        return updated

    async def mark_trace_delivered(
        self,
        trace_id: str,
        *,
        response_id: str,
    ) -> MemoryRecallTraceBundle:
        return await self._repository.complete_recall_trace(
            trace_id,
            response_id=response_id,
        )

    async def recall_trace(self, trace_id: str) -> MemoryRecallTraceBundle:
        return await self._repository.get_recall_trace(trace_id)

    async def recall_traces(self, *, limit: int) -> list[MemoryRecallTrace]:
        return await self._repository.list_recall_traces(limit=limit)

    async def exact_facts(
        self,
        *,
        entity_id: str,
        fact_keys: list[str],
        owner: bool,
    ) -> list[MemoryNode]:
        facts: list[MemoryNode] = []
        for fact_key in fact_keys:
            fact = await self._repository.exact_fact(
                entity_id=entity_id,
                memory_key=fact_key,
                actor_id=entity_id,
                conversation_id=None,
                owner=owner,
            )
            if fact is not None:
                facts.append(fact)
        return facts

    async def start_probe_trace(
        self,
        *,
        entity_id: str,
        prompt: str,
        facts: list[MemoryNode],
    ) -> MemoryRecallTraceBundle:
        trace_create = MemoryRecallTraceCreate(
            event_id=str(uuid4()),
            conversation_id=f"memory-probe:{entity_id}",
            actor_id=entity_id,
            route="probe",
            query_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )
        return await self._repository.create_recall_trace(
            trace_create,
            items=[
                MemoryRecallTraceItemCreate(
                    trace_id=trace_create.trace_id,
                    memory_id=fact.id,
                    memory_layer=MemoryLayer.FACT,
                    selection_reason="owner_isolation_probe",
                    lexical_score=1.0,
                    final_score=1.0,
                    selected=True,
                )
                for fact in facts
            ],
        )

    @staticmethod
    def fact_card(memory: MemoryNode) -> dict[str, object]:
        content = memory.content if isinstance(memory.content, dict) else {}
        return {
            "id": memory.id,
            "schema": content.get("schema"),
            "key": memory.memory_key or content.get("key"),
            "value": content.get("value"),
            "cardinality": content.get("cardinality"),
            "entity_id": memory.entity_id,
            "confidence": memory.confidence,
            "version": memory.version,
            "source_event_ids": memory.source_event_ids,
        }

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
        """Write the legacy recall ledger without asserting causal model use."""

        usage = await self._repository.record_usage(
            memory_id,
            response_id=response_id,
            conversation_id=conversation_id,
        )
        await self._audit.append(
            action="memory.legacy_recall_recorded",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="recorded",
            details={
                "memory_id": memory_id,
                "response_id": response_id,
                "causal_use_known": False,
            },
        )
        return usage

    async def _audit_change(self, action: str, memory: MemoryNode, *, actor_id: str) -> None:
        await self._audit.append(
            action=action,
            actor_id=actor_id,
            outcome="success",
            details={"memory_id": memory.id, "version": memory.version},
        )

    async def _audit_candidate_application(
        self,
        candidate: MemoryCandidate,
        *,
        actor_id: str,
        outcome: str,
        decision: MemoryFirewallDecision,
        replay_candidate: MemoryCandidate | None = None,
        memory: MemoryNode | None = None,
    ) -> None:
        await self._audit.append(
            action="memory.candidate_applied",
            actor_id=actor_id,
            outcome=outcome,
            details={
                "candidate_id": candidate.candidate_id,
                "replay_candidate_id": (
                    replay_candidate.candidate_id if replay_candidate is not None else None
                ),
                "memory_id": memory.id if memory is not None else None,
                "reason_code": decision.reason_code,
                "source_event_ids": candidate.source_event_ids,
            },
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
