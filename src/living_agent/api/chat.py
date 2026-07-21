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
    utterance_turn = await runtime.begin_utterance_turn(
        envelope.conversation_id,
        platform="chat_api",
    )
    result = await runtime.handle_chat(envelope)
    if not await runtime.activate_utterance(utterance_turn, result):
        return result
    for unit_index, _message in enumerate(result.messages):
        if utterance_turn is not None:
            if not await runtime.wait_for_utterance_unit(
                utterance_turn,
                result,
                unit_index=unit_index,
            ):
                if result.utterance is not None:
                    result.messages = result.messages[: result.utterance.sent_count]
                    result.message = result.messages[0] if result.messages else None
                break
            if not await runtime.mark_utterance_unit_started(
                utterance_turn,
                result,
                unit_index=unit_index,
            ):
                if result.utterance is not None:
                    result.messages = result.messages[: result.utterance.sent_count]
                    result.message = result.messages[0] if result.messages else None
                break
        await runtime.record_delivery(result, unit_index=unit_index, platform="chat_api")
    return result
