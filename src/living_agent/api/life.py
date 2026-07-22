"""Owner-only Phase 8 API for daily life, sleep, dreams, and change proposals."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from living_agent.api.dependencies import (
    get_authority,
    get_life_service,
    get_self_change_service,
)
from living_agent.api.management import ActorHeader, require_owner
from living_agent.life.repository import LifeConflictError, LifeNotFoundError, LifeStateError
from living_agent.life.self_change import SelfChangeService
from living_agent.life.service import LifeService
from living_agent.management.artifacts import (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStateError,
)
from living_agent.models.life import (
    DailyPlan,
    DailyPlanUpsert,
    DiaryEntry,
    DiaryUpsert,
    DreamRecord,
    LifeActivityCreate,
    LifeActivityFinish,
    LifeActivityLog,
    PlanItemStatusUpdate,
    PrivateProject,
    PrivateProjectCreate,
    PrivateProjectUpdate,
    SelfChangeProposal,
    SelfChangeProposalCreate,
    SleepCycle,
    SleepCycleRequest,
)
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/life", tags=["life"])
AuthorityDependency = Annotated[AuthorityResolver, Depends(get_authority)]
LifeDependency = Annotated[LifeService, Depends(get_life_service)]
SelfChangeDependency = Annotated[SelfChangeService, Depends(get_self_change_service)]
SelfChangeError = (
    LifeNotFoundError,
    LifeConflictError,
    LifeStateError,
    ArtifactNotFoundError,
    ArtifactConflictError,
    ArtifactStateError,
    PermissionError,
    ValueError,
)


def _life_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (LifeNotFoundError, ArtifactNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (LifeConflictError, ArtifactConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (LifeStateError, ArtifactStateError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="life operation failed")


@router.post("/projects", response_model=PrivateProject, status_code=status.HTTP_201_CREATED)
async def create_project(
    create: PrivateProjectCreate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> PrivateProject:
    require_owner(actor_id, authority)
    return await life.create_project(create, actor_id=actor_id)


@router.get("/projects", response_model=list[PrivateProject])
async def list_projects(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PrivateProject]:
    require_owner(actor_id, authority)
    return await life.projects(include_archived=include_archived, limit=limit)


@router.get("/projects/{project_id}", response_model=PrivateProject)
async def get_project(
    project_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> PrivateProject:
    require_owner(actor_id, authority)
    try:
        return await life.get_project(project_id)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.patch("/projects/{project_id}", response_model=PrivateProject)
async def update_project(
    project_id: str,
    update: PrivateProjectUpdate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> PrivateProject:
    require_owner(actor_id, authority)
    try:
        return await life.update_project(project_id, update, actor_id=actor_id)
    except (LifeNotFoundError, LifeConflictError, ValueError) as exc:
        raise _life_error(exc) from exc


@router.put("/daily-plans/{plan_date}", response_model=DailyPlan)
async def save_daily_plan(
    plan_date: date,
    request: DailyPlanUpsert,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DailyPlan:
    require_owner(actor_id, authority)
    try:
        return await life.upsert_plan(plan_date, request, actor_id=actor_id)
    except (LifeNotFoundError, LifeConflictError, ValueError) as exc:
        raise _life_error(exc) from exc


@router.get("/daily-plans", response_model=list[DailyPlan])
async def list_daily_plans(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DailyPlan]:
    require_owner(actor_id, authority)
    try:
        return await life.plans(start=start, end=end, limit=limit)
    except ValueError as exc:
        raise _life_error(exc) from exc


@router.get("/daily-plans/{plan_date}", response_model=DailyPlan)
async def get_daily_plan(
    plan_date: date,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DailyPlan:
    require_owner(actor_id, authority)
    try:
        return await life.get_plan(plan_date)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.post("/daily-plans/{plan_date}/items/{item_id}/status", response_model=DailyPlan)
async def transition_daily_plan_item(
    plan_date: date,
    item_id: str,
    update: PlanItemStatusUpdate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DailyPlan:
    require_owner(actor_id, authority)
    try:
        return await life.transition_plan_item(
            plan_date,
            item_id,
            update,
            actor_id=actor_id,
        )
    except (LifeNotFoundError, LifeConflictError, LifeStateError) as exc:
        raise _life_error(exc) from exc


@router.post("/activities", response_model=LifeActivityLog, status_code=status.HTTP_201_CREATED)
async def start_activity(
    create: LifeActivityCreate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> LifeActivityLog:
    require_owner(actor_id, authority)
    try:
        return await life.start_activity(create, actor_id=actor_id)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.post("/activities/{activity_id}/finish", response_model=LifeActivityLog)
async def finish_activity(
    activity_id: str,
    finish: LifeActivityFinish,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> LifeActivityLog:
    require_owner(actor_id, authority)
    try:
        return await life.finish_activity(activity_id, finish, actor_id=actor_id)
    except (LifeNotFoundError, LifeStateError) as exc:
        raise _life_error(exc) from exc


@router.get("/activities", response_model=list[LifeActivityLog])
async def list_activities(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[LifeActivityLog]:
    require_owner(actor_id, authority)
    return await life.activities(limit=limit)


@router.put("/diary/{entry_date}", response_model=DiaryEntry)
async def save_diary(
    entry_date: date,
    request: DiaryUpsert,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DiaryEntry:
    require_owner(actor_id, authority)
    try:
        return await life.upsert_diary(entry_date, request, actor_id=actor_id)
    except (LifeNotFoundError, LifeConflictError, ValueError) as exc:
        raise _life_error(exc) from exc


@router.get("/diary", response_model=list[DiaryEntry])
async def list_diaries(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DiaryEntry]:
    require_owner(actor_id, authority)
    return await life.diaries(limit=limit)


@router.get("/diary/{entry_date}", response_model=DiaryEntry)
async def get_diary(
    entry_date: date,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DiaryEntry:
    require_owner(actor_id, authority)
    try:
        return await life.get_diary(entry_date)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.post("/sleep-cycles/run", response_model=SleepCycle)
async def run_sleep_cycle(
    request: SleepCycleRequest,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> SleepCycle:
    require_owner(actor_id, authority)
    target_date = request.cycle_date or datetime.now(life.timezone).date()
    try:
        return await life.run_sleep_cycle(
            target_date,
            actor_id=actor_id,
            trigger="owner",
        )
    except (LifeNotFoundError, LifeConflictError, LifeStateError, ValueError) as exc:
        raise _life_error(exc) from exc


@router.get("/sleep-cycles", response_model=list[SleepCycle])
async def list_sleep_cycles(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SleepCycle]:
    require_owner(actor_id, authority)
    return await life.sleep_cycles(limit=limit)


@router.get("/dreams", response_model=list[DreamRecord])
async def list_dreams(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DreamRecord]:
    require_owner(actor_id, authority)
    return await life.dreams(limit=limit)


@router.get("/dreams/{dream_id}", response_model=DreamRecord)
async def get_dream(
    dream_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    life: LifeDependency,
) -> DreamRecord:
    require_owner(actor_id, authority)
    try:
        return await life.get_dream(dream_id)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.post(
    "/self-change-proposals",
    response_model=SelfChangeProposal,
    status_code=status.HTTP_201_CREATED,
)
async def submit_self_change_proposal(
    create: SelfChangeProposalCreate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    changes: SelfChangeDependency,
) -> SelfChangeProposal:
    require_owner(actor_id, authority)
    try:
        return await changes.submit(create)
    except SelfChangeError as exc:
        raise _life_error(exc) from exc


@router.get("/self-change-proposals", response_model=list[SelfChangeProposal])
async def list_self_change_proposals(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    changes: SelfChangeDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SelfChangeProposal]:
    require_owner(actor_id, authority)
    return await changes.proposals(limit=limit)


@router.get("/self-change-proposals/{proposal_id}", response_model=SelfChangeProposal)
async def get_self_change_proposal(
    proposal_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    changes: SelfChangeDependency,
) -> SelfChangeProposal:
    require_owner(actor_id, authority)
    try:
        return await changes.get(proposal_id)
    except LifeNotFoundError as exc:
        raise _life_error(exc) from exc


@router.post("/self-change-proposals/{proposal_id}/approve", response_model=SelfChangeProposal)
async def approve_self_change_proposal(
    proposal_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    changes: SelfChangeDependency,
) -> SelfChangeProposal:
    require_owner(actor_id, authority)
    try:
        return await changes.approve(proposal_id, actor_id=actor_id)
    except SelfChangeError as exc:
        raise _life_error(exc) from exc


@router.post("/self-change-proposals/{proposal_id}/reject", response_model=SelfChangeProposal)
async def reject_self_change_proposal(
    proposal_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    changes: SelfChangeDependency,
) -> SelfChangeProposal:
    require_owner(actor_id, authority)
    try:
        return await changes.reject(proposal_id, actor_id=actor_id)
    except SelfChangeError as exc:
        raise _life_error(exc) from exc
