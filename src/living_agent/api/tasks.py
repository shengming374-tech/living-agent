"""Owner control API for persistent executive tasks and confirmations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from living_agent.api.dependencies import get_authority, get_task_service
from living_agent.api.management import ActorHeader, require_owner
from living_agent.execution.contracts import TaskReport, TaskRun, TaskRunStatus
from living_agent.execution.repository import (
    TaskConflictError,
    TaskNotFoundError,
    TaskStateError,
)
from living_agent.execution.service import TaskService
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])
TaskIdPath = Annotated[
    str,
    Path(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    ),
]


def _task_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaskNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (TaskStateError, TaskConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task operation failed")


@router.get("", response_model=list[TaskRun])
async def list_tasks(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
    task_status: Annotated[TaskRunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TaskRun]:
    require_owner(actor_id, authority)
    return await tasks.list(status=task_status, limit=limit)


@router.get("/{task_id}", response_model=TaskRun)
async def get_task(
    task_id: TaskIdPath,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> TaskRun:
    require_owner(actor_id, authority)
    try:
        return await tasks.get(task_id)
    except Exception as exc:
        raise _task_error(exc) from exc


@router.post("/{task_id}/confirm", response_model=TaskRun)
async def confirm_task(
    task_id: TaskIdPath,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> TaskRun:
    require_owner(actor_id, authority)
    try:
        return await tasks.confirm(task_id=task_id, conversation_id=None, actor_id=actor_id)
    except Exception as exc:
        raise _task_error(exc) from exc


@router.post("/{task_id}/cancel", response_model=TaskRun)
async def cancel_task(
    task_id: TaskIdPath,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> TaskRun:
    require_owner(actor_id, authority)
    try:
        return await tasks.cancel(task_id=task_id, actor_id=actor_id)
    except Exception as exc:
        raise _task_error(exc) from exc


@router.get("/{task_id}/report", response_model=TaskReport)
async def get_task_report(
    task_id: TaskIdPath,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> TaskReport:
    require_owner(actor_id, authority)
    try:
        return await tasks.report(task_id)
    except Exception as exc:
        raise _task_error(exc) from exc
