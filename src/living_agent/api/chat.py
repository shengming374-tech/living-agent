"""Minimal trusted chat ingress."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from living_agent.api.dependencies import get_authority, get_runtime
from living_agent.api.management import ActorHeader, require_owner
from living_agent.models.conversation import ChatResult
from living_agent.models.events import IngressEnvelope, TrustedEvent
from living_agent.runtime.runtime import AgentRuntime
from living_agent.storage.events import EventRepository
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.management_auth import ManagementAuthenticator

router = APIRouter(prefix="/v1", tags=["chat"])


@router.get("/chat/history", response_model=list[TrustedEvent])
async def history(
    request: Request,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    conversation_id: Annotated[str, Query(min_length=1, max_length=255)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TrustedEvent]:
    require_owner(actor_id, authority)
    events: EventRepository = request.app.state.event_repository
    return await events.recent_for_conversation(conversation_id, limit=limit)


@router.post("/chat", response_model=ChatResult)
async def chat(
    envelope: IngressEnvelope,
    request: Request,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> ChatResult:
    if envelope.authenticated:
        authenticator: ManagementAuthenticator = request.app.state.management_authenticator
        reason_code = authenticator.rejection_reason(request.headers.get("Authorization"))
        if reason_code is not None:
            await request.app.state.audit.append(
                action="chat.auth",
                actor_id=envelope.source_identity,
                outcome="rejected",
                details={"reason_code": reason_code},
            )
            status_code = 401 if reason_code.endswith("missing") else 403
            raise HTTPException(
                status_code=status_code,
                detail=reason_code,
                headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
            )
    result, utterance_turn = await runtime.handle_platform_chat(
        envelope,
        platform="chat_api",
    )
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
