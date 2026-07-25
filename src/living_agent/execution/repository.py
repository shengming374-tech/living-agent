"""Persistent task runs with optimistic updates and idempotent reports."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.execution.contracts import (
    ExecutionPlan,
    TaskPlanProposal,
    TaskReport,
    TaskRun,
    TaskRunStatus,
    TaskStepResult,
)
from living_agent.execution.models import TaskReportORM, TaskRunORM
from living_agent.models.tasks import TaskContract


class TaskNotFoundError(LookupError):
    pass


class TaskConflictError(RuntimeError):
    pass


class TaskStateError(RuntimeError):
    pass


class TaskRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        proposal: TaskPlanProposal,
        *,
        activity_id: str | None,
    ) -> TaskRun:
        first_request = proposal.plan.steps[0].action.capability_request
        now = datetime.now(UTC)
        run = TaskRun(
            task=proposal.task,
            plan=proposal.plan,
            step_results=[TaskStepResult(step_id=step.step_id) for step in proposal.plan.steps],
            conversation_id=first_request.conversation_id,
            source_event_ids=list(first_request.source_event_ids),
            taint_labels=set(first_request.taint_labels),
            activity_id=activity_id,
            created_at=now,
            updated_at=now,
        )
        record = self._record(run)
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return run

    async def save(self, run: TaskRun) -> TaskRun:
        expected_version = run.version
        updated_at = datetime.now(UTC)
        statement = (
            update(TaskRunORM)
            .where(
                TaskRunORM.task_id == run.task.task_id,
                TaskRunORM.version == expected_version,
            )
            .values(
                status=run.status.value,
                step_results=[item.model_dump(mode="json") for item in run.step_results],
                pending_step_id=run.pending_step_id,
                activity_id=run.activity_id,
                updated_at=updated_at,
                version=expected_version + 1,
            )
            .returning(TaskRunORM)
        )
        async with self._sessions() as session, session.begin():
            record = await session.scalar(statement)
            if record is None:
                raise TaskConflictError("task run changed concurrently")
        return self._schema(record)

    async def get(self, task_id: str) -> TaskRun:
        async with self._sessions() as session:
            record = await session.get(TaskRunORM, task_id)
            if record is None:
                raise TaskNotFoundError("task run not found")
        return self._schema(record)

    async def list_runs(
        self,
        *,
        status: TaskRunStatus | None,
        limit: int,
    ) -> list[TaskRun]:
        statement = select(TaskRunORM)
        if status is not None:
            statement = statement.where(TaskRunORM.status == status.value)
        statement = statement.order_by(TaskRunORM.updated_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._schema(record) for record in records]

    async def latest_waiting(self, conversation_id: str | None) -> TaskRun:
        statement = (
            select(TaskRunORM)
            .where(
                TaskRunORM.conversation_id == conversation_id,
                TaskRunORM.status == TaskRunStatus.WAITING_CONFIRMATION.value,
            )
            .order_by(TaskRunORM.updated_at.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
            if record is None:
                raise TaskNotFoundError("no task is waiting for confirmation")
        return self._schema(record)

    async def latest_for_conversation(self, conversation_id: str | None) -> TaskRun:
        statement = (
            select(TaskRunORM)
            .where(TaskRunORM.conversation_id == conversation_id)
            .order_by(TaskRunORM.updated_at.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
            if record is None:
                raise TaskNotFoundError("no task exists in this conversation")
        return self._schema(record)

    async def recoverable_runs(self, *, limit: int = 100) -> list[TaskRun]:
        statement = (
            select(TaskRunORM)
            .where(
                TaskRunORM.status.in_([TaskRunStatus.PLANNED.value, TaskRunStatus.RUNNING.value])
            )
            .order_by(TaskRunORM.updated_at.asc())
            .limit(limit)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._schema(record) for record in records]

    async def terminal_runs_with_activities(self, *, limit: int = 100) -> list[TaskRun]:
        statement = (
            select(TaskRunORM)
            .where(
                TaskRunORM.status.in_(
                    [
                        TaskRunStatus.COMPLETED.value,
                        TaskRunStatus.FAILED.value,
                        TaskRunStatus.CANCELLED.value,
                    ]
                ),
                TaskRunORM.activity_id.is_not(None),
            )
            .order_by(TaskRunORM.updated_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._schema(record) for record in records]

    async def write_report(
        self,
        *,
        task_id: str,
        content: str,
        created_by: str,
        source_event_ids: list[str],
    ) -> TaskReport:
        existing = await self._find_report(task_id)
        if existing is not None:
            return self._require_matching_report(existing, content, created_by)
        try:
            return await self._insert_report(
                task_id=task_id,
                content=content,
                created_by=created_by,
                source_event_ids=source_event_ids,
            )
        except IntegrityError:
            existing = await self._find_report(task_id)
            if existing is None:
                raise
            return self._require_matching_report(existing, content, created_by)

    async def _insert_report(
        self,
        *,
        task_id: str,
        content: str,
        created_by: str,
        source_event_ids: list[str],
    ) -> TaskReport:
        async with self._sessions() as session, session.begin():
            record = TaskReportORM(
                report_id=str(uuid4()),
                task_id=task_id,
                content=content,
                created_by=created_by,
                source_event_ids=source_event_ids,
                created_at=datetime.now(UTC),
            )
            session.add(record)
        return self._report(record)

    async def _find_report(self, task_id: str) -> TaskReportORM | None:
        statement = select(TaskReportORM).where(TaskReportORM.task_id == task_id)
        async with self._sessions() as session:
            record: TaskReportORM | None = await session.scalar(statement)
        return record

    def _require_matching_report(
        self,
        existing: TaskReportORM,
        content: str,
        created_by: str,
    ) -> TaskReport:
        if existing.content != content or existing.created_by != created_by:
            raise TaskConflictError("task report already exists with different content")
        return self._report(existing)

    async def get_report(self, task_id: str) -> TaskReport:
        statement = select(TaskReportORM).where(TaskReportORM.task_id == task_id)
        async with self._sessions() as session:
            record = await session.scalar(statement)
            if record is None:
                raise TaskNotFoundError("task report not found")
        return self._report(record)

    @staticmethod
    def _record(run: TaskRun) -> TaskRunORM:
        return TaskRunORM(
            task_id=run.task.task_id,
            requester_id=run.task.requester_id,
            conversation_id=run.conversation_id,
            task_contract=run.task.model_dump(mode="json"),
            execution_plan=run.plan.model_dump(mode="json"),
            status=run.status.value,
            step_results=[item.model_dump(mode="json") for item in run.step_results],
            source_event_ids=run.source_event_ids,
            taint_labels=sorted(run.taint_labels),
            pending_step_id=run.pending_step_id,
            activity_id=run.activity_id,
            created_at=run.created_at,
            updated_at=run.updated_at,
            version=run.version,
        )

    @staticmethod
    def _schema(record: TaskRunORM) -> TaskRun:
        return TaskRun(
            task=TaskContract.model_validate(record.task_contract),
            plan=ExecutionPlan.model_validate(record.execution_plan),
            status=TaskRunStatus(record.status),
            step_results=[TaskStepResult.model_validate(item) for item in record.step_results],
            conversation_id=record.conversation_id,
            source_event_ids=record.source_event_ids,
            taint_labels=set(record.taint_labels),
            pending_step_id=record.pending_step_id,
            activity_id=record.activity_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            version=record.version,
        )

    @staticmethod
    def _report(record: TaskReportORM) -> TaskReport:
        return TaskReport(
            report_id=record.report_id,
            task_id=record.task_id,
            content=record.content,
            created_by=record.created_by,
            source_event_ids=record.source_event_ids,
            created_at=record.created_at,
        )
