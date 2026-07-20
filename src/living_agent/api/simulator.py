"""Owner-only, side-effect-free behavior simulation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from living_agent.api.dependencies import get_authority, get_runtime
from living_agent.api.management import ActorHeader, require_owner
from living_agent.evaluation.simulator import BehaviorSimulation
from living_agent.models.events import IngressEnvelope
from living_agent.runtime.runtime import AgentRuntime
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/simulator", tags=["simulator"])


@router.post("/turn", response_model=BehaviorSimulation)
async def simulate_turn(
    envelope: IngressEnvelope,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> BehaviorSimulation:
    require_owner(actor_id, authority)
    return await runtime.simulate_chat(envelope)
