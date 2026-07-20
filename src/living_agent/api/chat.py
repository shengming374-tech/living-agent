"""Minimal trusted chat ingress."""

from typing import Annotated

from fastapi import APIRouter, Depends

from living_agent.api.dependencies import get_runtime
from living_agent.models.conversation import ChatResult
from living_agent.models.events import IngressEnvelope
from living_agent.runtime.runtime import AgentRuntime

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResult)
async def chat(
    envelope: IngressEnvelope,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> ChatResult:
    return await runtime.handle_chat(envelope)
