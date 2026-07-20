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
    result = await runtime.handle_chat(envelope)
    for unit_index, _message in enumerate(result.messages):
        await runtime.record_delivery(result, unit_index=unit_index, platform="chat_api")
    return result
