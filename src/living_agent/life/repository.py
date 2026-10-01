"""Persistence for private daily-life, sleep, dream, and self-change records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.life.models import (
    DailyPlanORM,
    DiaryEntryORM,
    DreamRecordORM,
    LifeActivityLogORM,
    PrivateProjectORM,
    SelfChangeProposalORM,
    SleepCycleORM,
)
from living_agent.models.life import (
    DailyPlan,
    DailyPlanItemInput,
    DailyPlanStatus,
    DailyPlanUpsert,
    DiaryEntry,
    DiaryUpsert,
    DreamRecord,
    LifeActivityCreate,
    LifeActivityFinish,
    LifeActivityLog,
    LifeActivityStatus,
    PlanItemStatus,
    PrivateProject,
    PrivateProjectCreate,
    PrivateProjectUpdate,
    ProjectStatus,
    SelfChangeProposal,
    SelfChangeProposalCreate,
    SelfChangeProposalStatus,
    SleepCycle,
    SleepCycleStatus,
)


class LifeNotFoundError(LookupError):
    pass


class LifeConflictError(RuntimeError):
    pass


class LifeStateError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class LifeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_project(self, create: PrivateProjectCreate) -> PrivateProject:
        now = _now()
        record = PrivateProjectORM(
            project_id=str(uuid4()),
            title=create.title,
            summary=create.summary,
            goals=create.goals,
            status=ProjectStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
            version=1,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._project(record)

    async def projects(
        self,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[PrivateProject]:
        statement = select(PrivateProjectORM)
        if not include_archived:
            statement = statement.where(PrivateProjectORM.status != ProjectStatus.ARCHIVED.value)
        statement = statement.order_by(PrivateProjectORM.updated_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._project(record) for record in records]

    async def get_project(self, project_id: str) -> PrivateProject:
        async with self._sessions() as session:
            record = await session.get(PrivateProjectORM, project_id)
        if record is None:
            raise LifeNotFoundError("private project not found")
        return self._project(record)

    async def update_project(
        self,
        project_id: str,
        update: PrivateProjectUpdate,
    ) -> PrivateProject:
        async with self._sessions() as session, session.begin():
            record = await session.get(PrivateProjectORM, project_id)
            if record is None:
                raise LifeNotFoundError("private project not found")
            self._require_version(record.version, update.expected_version)
            changes = update.model_dump(exclude={"expected_version"}, exclude_unset=True)
            if any(value is None for value in changes.values()):
                raise ValueError("project update fields cannot be null")
            for field, value in changes.items():
                setattr(record, field, value.value if isinstance(value, ProjectStatus) else value)
            record.version += 1
            record.updated_at = _now()
        return self._project(record)

    async def upsert_plan(self, plan_date: date, request: DailyPlanUpsert) -> DailyPlan:
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(DailyPlanORM).where(DailyPlanORM.plan_date == plan_date)
            )
            now = _now()
            packed_items = [item.model_dump(mode="json") for item in request.items]
            status = self._plan_status(request.items)
            if record is None:
                if request.expected_version is not None:
                    raise LifeConflictError("daily plan does not exist at expected version")
                record = DailyPlanORM(
                    plan_id=str(uuid4()),
                    plan_date=plan_date,
                    intention=request.intention,
                    items=packed_items,
                    status=status.value,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                session.add(record)
            else:
                if request.expected_version is None:
                    raise LifeConflictError("expected_version is required to replace a daily plan")
                self._require_version(record.version, request.expected_version)
                record.intention = request.intention
                record.items = packed_items
                record.status = status.value
                record.updated_at = now
                record.version += 1
        return self._plan(record)

    async def get_plan(self, plan_date: date) -> DailyPlan:
        async with self._sessions() as session:
            record = await session.scalar(
                select(DailyPlanORM).where(DailyPlanORM.plan_date == plan_date)
            )
        if record is None:
            raise LifeNotFoundError("daily plan not found")
        return self._plan(record)

    async def plans(
        self,
        *,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[DailyPlan]:
        statement = select(DailyPlanORM)
        if start is not None:
            statement = statement.where(DailyPlanORM.plan_date >= start)
        if end is not None:
            statement = statement.where(DailyPlanORM.plan_date <= end)
        statement = statement.order_by(DailyPlanORM.plan_date.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._plan(record) for record in records]

    async def transition_plan_item(
        self,
        plan_date: date,
        item_id: str,
        *,
        expected_version: int,
        status: PlanItemStatus,
    ) -> tuple[DailyPlan, DailyPlanItemInput]:
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(DailyPlanORM).where(DailyPlanORM.plan_date == plan_date)
            )
            if record is None:
                raise LifeNotFoundError("daily plan not found")
            self._require_version(record.version, expected_version)
            items = [DailyPlanItemInput.model_validate(item) for item in record.items]
            target = next((item for item in items if item.item_id == item_id), None)
            if target is None:
                raise LifeNotFoundError("daily plan item not found")
            target = target.model_copy(update={"status": status})
            items = [target if item.item_id == item_id else item for item in items]
            record.items = [item.model_dump(mode="json") for item in items]
            record.status = self._plan_status(items).value
            record.version += 1
            record.updated_at = _now()
        return self._plan(record), target

    async def start_activity(self, create: LifeActivityCreate) -> LifeActivityLog:
        record = LifeActivityLogORM(
            activity_id=str(uuid4()),
            kind=create.kind,
            title=create.title,
            summary=create.summary,
            project_id=create.project_id,
            plan_id=create.plan_id,
            plan_item_id=create.plan_item_id,
            status=LifeActivityStatus.RUNNING.value,
            evidence_ids=[],
            started_at=_now(),
            finished_at=None,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._activity(record)

    async def activity_for_item(
        self,
        plan_id: str,
        plan_item_id: str,
    ) -> LifeActivityLog | None:
        statement = (
            select(LifeActivityLogORM)
            .where(
                LifeActivityLogORM.plan_id == plan_id,
                LifeActivityLogORM.plan_item_id == plan_item_id,
            )
            .order_by(LifeActivityLogORM.started_at.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
        return self._activity(record) if record is not None else None

    async def running_plan_activities(self, plan_id: str) -> list[LifeActivityLog]:
        statement = select(LifeActivityLogORM).where(
            LifeActivityLogORM.plan_id == plan_id,
            LifeActivityLogORM.status == LifeActivityStatus.RUNNING.value,
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._activity(record) for record in records]

    async def finish_activity(
        self,
        activity_id: str,
        finish: LifeActivityFinish,
    ) -> LifeActivityLog:
        async with self._sessions() as session, session.begin():
            record = await session.get(LifeActivityLogORM, activity_id)
            if record is None:
                raise LifeNotFoundError("life activity not found")
            if record.status != LifeActivityStatus.RUNNING.value:
                raise LifeStateError("only a running life activity can be finished")
            record.status = finish.status.value
            record.evidence_ids = finish.evidence_ids
            if finish.summary is not None:
                record.summary = finish.summary
            record.finished_at = _now()
        return self._activity(record)

    async def activities(
        self,
        *,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 200,
    ) -> list[LifeActivityLog]:
        statement = select(LifeActivityLogORM)
        if started_after is not None:
            statement = statement.where(LifeActivityLogORM.started_at >= started_after)
        if started_before is not None:
            statement = statement.where(LifeActivityLogORM.started_at < started_before)
        statement = statement.order_by(LifeActivityLogORM.started_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._activity(record) for record in records]

    async def get_activity(self, activity_id: str) -> LifeActivityLog:
        async with self._sessions() as session:
            record = await session.get(LifeActivityLogORM, activity_id)
        if record is None:
            raise LifeNotFoundError("life activity not found")
        return self._activity(record)

    async def upsert_diary(
        self,
        entry_date: date,
        request: DiaryUpsert,
        *,
        generated_by: str,
    ) -> DiaryEntry:
        async with self._sessions() as session, session.begin():
            record = await session.scalar(
                select(DiaryEntryORM).where(DiaryEntryORM.entry_date == entry_date)
            )
            now = _now()
            if record is None:
                if request.expected_version is not None:
                    raise LifeConflictError("diary entry does not exist at expected version")
                record = DiaryEntryORM(
                    diary_id=str(uuid4()),
                    entry_date=entry_date,
                    content=request.content,
                    mood_summary=request.mood_summary,
                    status=request.status.value,
                    generated_by=generated_by,
                    source_activity_ids=request.source_activity_ids,
                    source_memory_ids=request.source_memory_ids,
                    dream_record_ids=request.dream_record_ids,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                session.add(record)
            else:
                if request.expected_version is None:
                    raise LifeConflictError("expected_version is required to replace a diary entry")
                self._require_version(record.version, request.expected_version)
                record.content = request.content
                record.mood_summary = request.mood_summary
                record.status = request.status.value
                record.generated_by = generated_by
                record.source_activity_ids = request.source_activity_ids
                record.source_memory_ids = request.source_memory_ids
                record.dream_record_ids = request.dream_record_ids
                record.updated_at = now
                record.version += 1
        return self._diary(record)

    async def get_diary(self, entry_date: date) -> DiaryEntry:
        async with self._sessions() as session:
            record = await session.scalar(
                select(DiaryEntryORM).where(DiaryEntryORM.entry_date == entry_date)
            )
        if record is None:
            raise LifeNotFoundError("diary entry not found")
        return self._diary(record)

    async def diaries(self, *, limit: int = 100) -> list[DiaryEntry]:
        statement = select(DiaryEntryORM).order_by(DiaryEntryORM.entry_date.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._diary(record) for record in records]

    async def begin_sleep_cycle(self, cycle_date: date, *, trigger: str) -> SleepCycle:
        existing = await self.sleep_cycle_for_date(cycle_date, required=False)
        if existing is not None:
            if existing.status is SleepCycleStatus.COMPLETED:
                return existing
            raise LifeConflictError("sleep cycle already exists for this date")
        record = SleepCycleORM(
            cycle_id=str(uuid4()),
            cycle_date=cycle_date,
            trigger=trigger,
            status=SleepCycleStatus.RUNNING.value,
            diary_id=None,
            dream_id=None,
            reality_memory_ids=[],
            candidate_review_ids=[],
            duplicate_memory_clusters=[],
            thought_record_ids=[],
            activity_ids=[],
            automatic_memory_writes=0,
            error_code=None,
            started_at=_now(),
            finished_at=None,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._sleep_cycle(record)

    async def complete_sleep_cycle(
        self,
        cycle_id: str,
        *,
        diary_id: str,
        dream_id: str,
        reality_memory_ids: list[str],
        candidate_review_ids: list[str],
        duplicate_memory_clusters: list[list[str]],
        thought_record_ids: list[str],
        activity_ids: list[str],
    ) -> SleepCycle:
        async with self._sessions() as session, session.begin():
            record = await session.get(SleepCycleORM, cycle_id)
            if record is None:
                raise LifeNotFoundError("sleep cycle not found")
            if record.status != SleepCycleStatus.RUNNING.value:
                raise LifeStateError("sleep cycle is not running")
            record.status = SleepCycleStatus.COMPLETED.value
            record.diary_id = diary_id
            record.dream_id = dream_id
            record.reality_memory_ids = reality_memory_ids
            record.candidate_review_ids = candidate_review_ids
            record.duplicate_memory_clusters = duplicate_memory_clusters
            record.thought_record_ids = thought_record_ids
            record.activity_ids = activity_ids
            record.automatic_memory_writes = 0
            record.finished_at = _now()
        return self._sleep_cycle(record)

    async def fail_sleep_cycle(self, cycle_id: str, *, error_code: str) -> SleepCycle:
        async with self._sessions() as session, session.begin():
            record = await session.get(SleepCycleORM, cycle_id)
            if record is None:
                raise LifeNotFoundError("sleep cycle not found")
            record.status = SleepCycleStatus.FAILED.value
            record.error_code = error_code[:100]
            record.finished_at = _now()
            record.automatic_memory_writes = 0
        return self._sleep_cycle(record)

    async def fail_interrupted_sleep_cycles(self) -> list[SleepCycle]:
        statement = select(SleepCycleORM).where(
            SleepCycleORM.status == SleepCycleStatus.RUNNING.value
        )
        async with self._sessions() as session, session.begin():
            records = list((await session.scalars(statement)).all())
            for record in records:
                record.status = SleepCycleStatus.FAILED.value
                record.error_code = "startup_interrupted"
                record.finished_at = _now()
                record.automatic_memory_writes = 0
        return [self._sleep_cycle(record) for record in records]

    async def sleep_cycle_for_date(
        self,
        cycle_date: date,
        *,
        required: bool = True,
    ) -> SleepCycle | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(SleepCycleORM).where(SleepCycleORM.cycle_date == cycle_date)
            )
        if record is None and required:
            raise LifeNotFoundError("sleep cycle not found")
        return self._sleep_cycle(record) if record is not None else None

    async def sleep_cycles(self, *, limit: int = 100) -> list[SleepCycle]:
        statement = select(SleepCycleORM).order_by(SleepCycleORM.cycle_date.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._sleep_cycle(record) for record in records]

    async def create_dream(
        self,
        *,
        cycle_id: str,
        dream_date: date,
        content: str,
        seed_activity_ids: list[str],
        seed_memory_ids: list[str],
    ) -> DreamRecord:
        record = DreamRecordORM(
            dream_id=str(uuid4()),
            cycle_id=cycle_id,
            dream_date=dream_date,
            content=content,
            seed_activity_ids=seed_activity_ids,
            seed_memory_ids=seed_memory_ids,
            factuality="dream",
            reality_eligible=False,
            created_at=_now(),
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._dream(record)

    async def get_dream(self, dream_id: str) -> DreamRecord:
        async with self._sessions() as session:
            record = await session.get(DreamRecordORM, dream_id)
        if record is None:
            raise LifeNotFoundError("dream record not found")
        return self._dream(record)

    async def dreams(self, *, limit: int = 100) -> list[DreamRecord]:
        statement = select(DreamRecordORM).order_by(DreamRecordORM.created_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._dream(record) for record in records]

    async def require_diary_ids(self, diary_ids: list[str]) -> None:
        if not diary_ids:
            return
        statement = select(DiaryEntryORM.diary_id).where(DiaryEntryORM.diary_id.in_(diary_ids))
        async with self._sessions() as session:
            found = set((await session.scalars(statement)).all())
        if found != set(diary_ids):
            raise LifeNotFoundError("one or more source diary entries do not exist")

    async def require_dream_ids(self, dream_ids: list[str]) -> None:
        if not dream_ids:
            return
        statement = select(DreamRecordORM.dream_id).where(DreamRecordORM.dream_id.in_(dream_ids))
        async with self._sessions() as session:
            found = set((await session.scalars(statement)).all())
        if found != set(dream_ids):
            raise LifeNotFoundError("one or more source dreams do not exist")

    async def create_proposal(
        self,
        create: SelfChangeProposalCreate,
        *,
        stage_id: str,
        diff: str,
        test_results: dict[str, object],
        status: SelfChangeProposalStatus,
    ) -> SelfChangeProposal:
        now = _now()
        record = SelfChangeProposalORM(
            proposal_id=str(uuid4()),
            proposer_id="living-agent",
            target_kind=create.target_kind.value,
            target_path=create.target_path,
            base_version=create.expected_version,
            proposed_content=create.proposed_content,
            rationale=create.rationale,
            source_diary_ids=create.source_diary_ids,
            source_dream_ids=create.source_dream_ids,
            stage_id=stage_id,
            diff=diff,
            test_results=test_results,
            status=status.value,
            approved_by=None,
            deployed_version=None,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._proposal(record)

    async def get_proposal(self, proposal_id: str) -> SelfChangeProposal:
        async with self._sessions() as session:
            record = await session.get(SelfChangeProposalORM, proposal_id)
        if record is None:
            raise LifeNotFoundError("self-change proposal not found")
        return self._proposal(record)

    async def proposals(self, *, limit: int = 100) -> list[SelfChangeProposal]:
        statement = (
            select(SelfChangeProposalORM)
            .order_by(SelfChangeProposalORM.created_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._proposal(record) for record in records]

    async def set_proposal_status(
        self,
        proposal_id: str,
        *,
        status: SelfChangeProposalStatus,
        approved_by: str | None = None,
        deployed_version: int | None = None,
    ) -> SelfChangeProposal:
        async with self._sessions() as session, session.begin():
            record = await session.get(SelfChangeProposalORM, proposal_id)
            if record is None:
                raise LifeNotFoundError("self-change proposal not found")
            record.status = status.value
            record.approved_by = approved_by
            record.deployed_version = deployed_version
            record.updated_at = _now()
        return self._proposal(record)

    @staticmethod
    def _require_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise LifeConflictError("record version does not match")

    @staticmethod
    def _plan_status(items: list[DailyPlanItemInput]) -> DailyPlanStatus:
        statuses = {item.status for item in items}
        if statuses <= {PlanItemStatus.COMPLETED, PlanItemStatus.SKIPPED}:
            return DailyPlanStatus.COMPLETED
        if statuses & {PlanItemStatus.IN_PROGRESS, PlanItemStatus.COMPLETED}:
            return DailyPlanStatus.ACTIVE
        return DailyPlanStatus.PLANNED

    @staticmethod
    def _project(record: PrivateProjectORM) -> PrivateProject:
        return PrivateProject.model_validate(record, from_attributes=True)

    @staticmethod
    def _plan(record: DailyPlanORM) -> DailyPlan:
        return DailyPlan.model_validate(record, from_attributes=True)

    @staticmethod
    def _activity(record: LifeActivityLogORM) -> LifeActivityLog:
        return LifeActivityLog.model_validate(record, from_attributes=True)

    @staticmethod
    def _diary(record: DiaryEntryORM) -> DiaryEntry:
        return DiaryEntry.model_validate(record, from_attributes=True)

    @staticmethod
    def _sleep_cycle(record: SleepCycleORM) -> SleepCycle:
        return SleepCycle.model_validate(record, from_attributes=True)

    @staticmethod
    def _dream(record: DreamRecordORM) -> DreamRecord:
        return DreamRecord.model_validate(record, from_attributes=True)

    @staticmethod
    def _proposal(record: SelfChangeProposalORM) -> SelfChangeProposal:
        return SelfChangeProposal.model_validate(record, from_attributes=True)
