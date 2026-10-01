"""Audited private projects, daily plans, diaries, sleep, and dream workflows."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from living_agent.audit.service import AuditService, redact_text
from living_agent.life.repository import LifeNotFoundError, LifeRepository
from living_agent.memory.service import MemoryService
from living_agent.models.life import (
    DailyPlan,
    DailyPlanUpsert,
    DiaryEntry,
    DiaryStatus,
    DiaryUpsert,
    DreamRecord,
    LifeActivityCreate,
    LifeActivityFinish,
    LifeActivityLog,
    LifeActivityStatus,
    PlanItemStatus,
    PlanItemStatusUpdate,
    PrivateProject,
    PrivateProjectCreate,
    PrivateProjectUpdate,
    SleepCycle,
)
from living_agent.models.memory import CandidateStatus, MemoryFactuality, MemoryNode
from living_agent.models.psyche import ThoughtRecord
from living_agent.psyche.service import PsycheService

_REALITY_FACTUALITIES = {
    MemoryFactuality.VERIFIED,
    MemoryFactuality.REPORTED,
    MemoryFactuality.INFERRED,
}


class LifeService:
    def __init__(
        self,
        *,
        repository: LifeRepository,
        memories: MemoryService,
        psyche: PsycheService,
        audit: AuditService,
        timezone: ZoneInfo,
    ) -> None:
        self._repository = repository
        self._memories = memories
        self._psyche = psyche
        self._audit = audit
        self._timezone = timezone
        self._sleep_lock = asyncio.Lock()
        self._plan_lock = asyncio.Lock()

    @property
    def timezone(self) -> ZoneInfo:
        return self._timezone

    async def initialize(self) -> None:
        interrupted = await self._repository.fail_interrupted_sleep_cycles()
        for cycle in interrupted:
            await self._audit.append(
                action="sleep_cycle.recovered",
                actor_id="living-agent",
                outcome="failed",
                details={
                    "cycle_id": cycle.cycle_id,
                    "cycle_date": cycle.cycle_date.isoformat(),
                    "reason_code": "startup_interrupted",
                    "automatic_memory_writes": 0,
                },
            )

    async def create_project(
        self,
        create: PrivateProjectCreate,
        *,
        actor_id: str,
    ) -> PrivateProject:
        project = await self._repository.create_project(create)
        await self._audit.append(
            action="life.project_created",
            actor_id=actor_id,
            outcome="success",
            details={"project_id": project.project_id},
        )
        return project

    async def projects(
        self,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[PrivateProject]:
        return await self._repository.projects(
            include_archived=include_archived,
            limit=limit,
        )

    async def get_project(self, project_id: str) -> PrivateProject:
        return await self._repository.get_project(project_id)

    async def update_project(
        self,
        project_id: str,
        update: PrivateProjectUpdate,
        *,
        actor_id: str,
    ) -> PrivateProject:
        project = await self._repository.update_project(project_id, update)
        await self._audit.append(
            action="life.project_updated",
            actor_id=actor_id,
            outcome="success",
            details={
                "project_id": project.project_id,
                "status": project.status.value,
                "version": project.version,
            },
        )
        return project

    async def upsert_plan(
        self,
        plan_date: date,
        request: DailyPlanUpsert,
        *,
        actor_id: str,
    ) -> DailyPlan:
        for item in request.items:
            if item.project_id is not None:
                project = await self._repository.get_project(item.project_id)
                if project.status.value == "archived":
                    raise ValueError("daily plan cannot reference an archived project")
        async with self._plan_lock:
            plan = await self._repository.upsert_plan(plan_date, request)
            await self._sync_plan_activities(plan, actor_id=actor_id)
        await self._audit.append(
            action="life.plan_saved",
            actor_id=actor_id,
            outcome="success",
            details={
                "plan_id": plan.plan_id,
                "plan_date": plan.plan_date.isoformat(),
                "item_count": len(plan.items),
                "version": plan.version,
            },
        )
        return plan

    async def get_plan(self, plan_date: date) -> DailyPlan:
        return await self._repository.get_plan(plan_date)

    async def plans(
        self,
        *,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[DailyPlan]:
        if start is not None and end is not None and start > end:
            raise ValueError("daily plan start date cannot be after end date")
        return await self._repository.plans(start=start, end=end, limit=limit)

    async def transition_plan_item(
        self,
        plan_date: date,
        item_id: str,
        update: PlanItemStatusUpdate,
        *,
        actor_id: str,
    ) -> DailyPlan:
        async with self._plan_lock:
            plan, _item = await self._repository.transition_plan_item(
                plan_date,
                item_id,
                expected_version=update.expected_version,
                status=update.status,
            )
            await self._sync_plan_activities(plan, actor_id=actor_id)
        await self._audit.append(
            action="life.plan_item_transitioned",
            actor_id=actor_id,
            outcome="success",
            details={
                "plan_id": plan.plan_id,
                "item_id": item_id,
                "status": update.status.value,
                "version": plan.version,
            },
        )
        return plan

    async def _sync_plan_activities(self, plan: DailyPlan, *, actor_id: str) -> None:
        """Keep replacements and status edits attached to this plan's activity history."""

        items = {item.item_id: item for item in plan.items}
        running = await self._repository.running_plan_activities(plan.plan_id)
        active_items: set[str] = set()
        for activity in running:
            item = items.get(activity.plan_item_id or "")
            if item is not None and item.status is PlanItemStatus.IN_PROGRESS:
                active_items.add(item.item_id)
                continue
            finish_status = (
                LifeActivityStatus.COMPLETED
                if item is not None and item.status is PlanItemStatus.COMPLETED
                else LifeActivityStatus.CANCELLED
            )
            finished = await self._repository.finish_activity(
                activity.activity_id,
                LifeActivityFinish(status=finish_status),
            )
            await self._audit_activity_finished(finished, actor_id=actor_id)
        for item in plan.items:
            if item.status not in {PlanItemStatus.IN_PROGRESS, PlanItemStatus.COMPLETED}:
                continue
            if item.item_id in active_items:
                continue
            if item.status is PlanItemStatus.COMPLETED:
                latest = await self._repository.activity_for_item(plan.plan_id, item.item_id)
                if latest is not None and latest.status is LifeActivityStatus.COMPLETED:
                    continue
            activity = await self._repository.start_activity(
                LifeActivityCreate(
                    kind=f"plan:{item.kind.value}",
                    title=item.title,
                    project_id=item.project_id,
                    plan_id=plan.plan_id,
                    plan_item_id=item.item_id,
                )
            )
            await self._audit_activity_started(activity, actor_id=actor_id)
            if item.status is PlanItemStatus.COMPLETED:
                finished = await self._repository.finish_activity(
                    activity.activity_id,
                    LifeActivityFinish(status=LifeActivityStatus.COMPLETED),
                )
                await self._audit_activity_finished(finished, actor_id=actor_id)

    async def start_activity(
        self,
        create: LifeActivityCreate,
        *,
        actor_id: str,
    ) -> LifeActivityLog:
        if create.project_id is not None:
            await self._repository.get_project(create.project_id)
        activity = await self._repository.start_activity(create)
        await self._audit_activity_started(activity, actor_id=actor_id)
        return activity

    async def finish_activity(
        self,
        activity_id: str,
        finish: LifeActivityFinish,
        *,
        actor_id: str,
    ) -> LifeActivityLog:
        activity = await self._repository.finish_activity(activity_id, finish)
        await self._audit_activity_finished(activity, actor_id=actor_id)
        return activity

    async def activities(self, *, limit: int = 200) -> list[LifeActivityLog]:
        return await self._repository.activities(limit=limit)

    async def upsert_diary(
        self,
        entry_date: date,
        request: DiaryUpsert,
        *,
        actor_id: str,
    ) -> DiaryEntry:
        await self._require_diary_sources(request)
        diary = await self._repository.upsert_diary(
            entry_date,
            request,
            generated_by=actor_id,
        )
        await self._audit.append(
            action="life.diary_saved",
            actor_id=actor_id,
            outcome="success",
            details={
                "diary_id": diary.diary_id,
                "entry_date": diary.entry_date.isoformat(),
                "status": diary.status.value,
                "version": diary.version,
            },
        )
        return diary

    async def get_diary(self, entry_date: date) -> DiaryEntry:
        return await self._repository.get_diary(entry_date)

    async def diaries(self, *, limit: int = 100) -> list[DiaryEntry]:
        return await self._repository.diaries(limit=limit)

    async def sleep_cycles(self, *, limit: int = 100) -> list[SleepCycle]:
        return await self._repository.sleep_cycles(limit=limit)

    async def dreams(self, *, limit: int = 100) -> list[DreamRecord]:
        return await self._repository.dreams(limit=limit)

    async def get_dream(self, dream_id: str) -> DreamRecord:
        return await self._repository.get_dream(dream_id)

    async def run_sleep_cycle(
        self,
        cycle_date: date,
        *,
        actor_id: str,
        trigger: str,
    ) -> SleepCycle:
        async with self._sleep_lock:
            existing = await self._repository.sleep_cycle_for_date(cycle_date, required=False)
            if existing is not None and existing.status.value == "completed":
                return existing
            cycle = await self._repository.begin_sleep_cycle(cycle_date, trigger=trigger)
            try:
                start, end = self._date_bounds(cycle_date)
                activities = await self._repository.activities(
                    started_after=start,
                    started_before=end,
                    limit=500,
                )
                thoughts = [
                    thought
                    for thought in await self._psyche.thoughts(
                        include_resolved=True,
                        limit=500,
                    )
                    if self._local_date(thought.created_at) == cycle_date
                ]
                memories = await self._memories.search(
                    actor_id=actor_id,
                    conversation_id=None,
                    owner=True,
                    query="",
                    include_deleted=False,
                    limit=500,
                )
                reality_memories = [
                    memory for memory in memories if memory.factuality in _REALITY_FACTUALITIES
                ]
                pending = await self._memories.candidates(
                    status=CandidateStatus.PENDING,
                    limit=500,
                )
                clusters = self._duplicate_clusters(reality_memories)
                dream = await self._repository.create_dream(
                    cycle_id=cycle.cycle_id,
                    dream_date=cycle_date,
                    content=self._dream_content(activities, reality_memories),
                    seed_activity_ids=[item.activity_id for item in activities[:8]],
                    seed_memory_ids=[item.id for item in reality_memories[:8]],
                )
                diary = await self._sleep_diary(
                    cycle_date,
                    activities=activities,
                    thoughts=thoughts,
                    reality_memory_ids=[item.id for item in reality_memories[:20]],
                    dream_id=dream.dream_id,
                )
                completed = await self._repository.complete_sleep_cycle(
                    cycle.cycle_id,
                    diary_id=diary.diary_id,
                    dream_id=dream.dream_id,
                    reality_memory_ids=[item.id for item in reality_memories],
                    candidate_review_ids=[item.candidate_id for item in pending],
                    duplicate_memory_clusters=clusters,
                    thought_record_ids=[item.thought_id for item in thoughts],
                    activity_ids=[item.activity_id for item in activities],
                )
            except Exception as exc:
                await self._repository.fail_sleep_cycle(
                    cycle.cycle_id,
                    error_code=type(exc).__name__,
                )
                await self._audit.append(
                    action="sleep_cycle.failed",
                    actor_id=actor_id,
                    outcome="failed",
                    details={
                        "cycle_id": cycle.cycle_id,
                        "cycle_date": cycle_date.isoformat(),
                        "error_code": type(exc).__name__,
                        "automatic_memory_writes": 0,
                    },
                )
                raise
        await self._audit.append(
            action="sleep_cycle.completed",
            actor_id=actor_id,
            outcome="success",
            details={
                "cycle_id": completed.cycle_id,
                "cycle_date": completed.cycle_date.isoformat(),
                "reality_memory_count": len(completed.reality_memory_ids),
                "candidate_review_count": len(completed.candidate_review_ids),
                "duplicate_cluster_count": len(completed.duplicate_memory_clusters),
                "automatic_memory_writes": 0,
                "dream_factuality": "dream",
            },
        )
        return completed

    async def _sleep_diary(
        self,
        entry_date: date,
        *,
        activities: list[LifeActivityLog],
        thoughts: Sequence[ThoughtRecord],
        reality_memory_ids: list[str],
        dream_id: str,
    ) -> DiaryEntry:
        try:
            return await self._repository.get_diary(entry_date)
        except LifeNotFoundError:
            pass
        completed_titles = [
            redact_text(item.title)
            for item in activities
            if item.status is LifeActivityStatus.COMPLETED
        ][:8]
        thought_summaries = [
            redact_text(str(getattr(item, "summary", ""))) for item in thoughts
        ][:5]
        lines = [f"{entry_date.isoformat()} 的记录。"]
        if completed_titles:
            lines.append(f"完成了: {'、'.join(completed_titles)}。")
        else:
            lines.append("今天没有留下已完成活动的证据。")
        if thought_summaries:
            lines.append(f"留意到的想法: {'; '.join(thought_summaries)}。")
        return await self._repository.upsert_diary(
            entry_date,
            DiaryUpsert(
                content="\n".join(lines),
                mood_summary="依据当天可观察记录生成的日记草稿",
                status=DiaryStatus.DRAFT,
                source_activity_ids=[item.activity_id for item in activities],
                source_memory_ids=reality_memory_ids,
                dream_record_ids=[dream_id],
            ),
            generated_by="sleep_cycle",
        )

    async def _require_diary_sources(self, request: DiaryUpsert) -> None:
        for activity_id in request.source_activity_ids:
            await self._repository.get_activity(activity_id)
        for memory_id in request.source_memory_ids:
            await self._memories.get_accessible(
                memory_id,
                actor_id="living-agent",
                conversation_id=None,
                owner=True,
            )
        await self._repository.require_dream_ids(request.dream_record_ids)

    async def _audit_activity_started(
        self,
        activity: LifeActivityLog,
        *,
        actor_id: str,
    ) -> None:
        await self._audit.append(
            action="life.activity_started",
            actor_id=actor_id,
            outcome="running",
            details={
                "activity_id": activity.activity_id,
                "project_id": activity.project_id,
                "plan_id": activity.plan_id,
                "plan_item_id": activity.plan_item_id,
            },
        )

    async def _audit_activity_finished(
        self,
        activity: LifeActivityLog,
        *,
        actor_id: str,
    ) -> None:
        await self._audit.append(
            action="life.activity_finished",
            actor_id=actor_id,
            outcome=activity.status.value,
            details={
                "activity_id": activity.activity_id,
                "evidence_ids": activity.evidence_ids,
            },
        )

    def _date_bounds(self, value: date) -> tuple[datetime, datetime]:
        start = datetime.combine(value, time.min, tzinfo=self._timezone)
        end = start + timedelta(days=1)
        return start.astimezone(UTC), end.astimezone(UTC)

    def _local_date(self, value: datetime) -> date:
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(self._timezone).date()

    @staticmethod
    def _duplicate_clusters(memories: Sequence[MemoryNode]) -> list[list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for memory in memories:
            subject = " ".join(str(getattr(memory, "subject", "")).casefold().split())
            memory_id = str(getattr(memory, "id", ""))
            if subject and memory_id:
                groups[subject].append(memory_id)
        return [ids for ids in groups.values() if len(ids) > 1]

    @staticmethod
    def _dream_content(
        activities: list[LifeActivityLog],
        memories: Sequence[MemoryNode],
    ) -> str:
        seeds = [redact_text(item.title) for item in activities[:3]]
        seeds.extend(
            redact_text(str(getattr(memory, "subject", ""))) for memory in memories[:3]
        )
        seeds = [seed for seed in seeds if seed]
        if not seeds:
            return "梦里是一座没有现实坐标的空舞台, 灯光慢慢亮起又熄灭。"
        return f"梦里, {'、'.join(seeds[:4])}在一座没有现实坐标的舞台上交叠。"
