"""Authenticated NapCat reverse-WebSocket ingress and brokered reply adapter."""

from __future__ import annotations

import asyncio
import hmac
import re
from typing import Any

from fastapi import WebSocket
from pydantic import SecretStr, ValidationError

from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.models.capabilities import (
    CapabilityGrant,
    CapabilityRequest,
    DecisionOutcome,
)
from living_agent.platforms.napcat.connection import (
    NapCatActionTimeoutError,
    NapCatConnection,
    NapCatConnectionError,
)
from living_agent.platforms.napcat.models import (
    NAPCAT_REPLY_CAPABILITY,
    NapCatReplyArguments,
    OneBotActionResponse,
    OneBotMessageEvent,
    OneBotMetaEvent,
    normalize_message,
    onebot_reply_action,
)
from living_agent.runtime.runtime import AgentRuntime

_SELF_ID_PATTERN = re.compile(r"^[0-9]{1,32}$")
_ALLOW_OUTCOMES = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}


class NapCatAdapter:
    def __init__(
        self,
        *,
        enabled: bool,
        access_token: SecretStr | None,
        runtime: AgentRuntime,
        broker: CapabilityBroker,
        audit: AuditService,
        action_timeout_seconds: float,
        max_message_chars: int,
        max_frame_bytes: int,
        max_in_flight_events: int,
    ) -> None:
        self._enabled = enabled
        self._access_token = access_token.get_secret_value() if access_token is not None else None
        self._runtime = runtime
        self._broker = broker
        self._audit = audit
        self._action_timeout_seconds = action_timeout_seconds
        self._max_message_chars = max_message_chars
        self._max_frame_bytes = max_frame_bytes
        self._max_in_flight_events = max_in_flight_events

    async def serve(self, websocket: WebSocket) -> None:
        self_id = websocket.headers.get("x-self-id")
        rejection = self._authentication_error(websocket, self_id)
        if rejection is not None:
            await self._audit.append(
                action="napcat.connection",
                actor_id=None,
                outcome="rejected",
                details={"reason_code": rejection},
            )
            await websocket.close(code=1008, reason="NapCat authentication failed")
            return
        assert self_id is not None
        await websocket.accept()
        actor_id = f"napcat:{self_id}"
        await self._audit.append(
            action="napcat.connection",
            actor_id=actor_id,
            outcome="connected",
            details={"self_id": self_id},
        )
        connection = NapCatConnection(
            websocket,
            action_timeout_seconds=self._action_timeout_seconds,
            max_frame_bytes=self._max_frame_bytes,
            max_in_flight_events=self._max_in_flight_events,
        )

        async def handle(frame: dict[str, Any], active: NapCatConnection) -> None:
            await self._handle_frame_guarded(frame, active, self_id=self_id)

        async def issue(reason_code: str) -> None:
            await self._audit.append(
                action="napcat.frame",
                actor_id=actor_id,
                outcome="rejected",
                details={"reason_code": reason_code},
            )

        try:
            await connection.run(handle, issue)
        except Exception as exc:
            await self._audit.append(
                action="napcat.connection",
                actor_id=actor_id,
                outcome="failure",
                details={"error_code": type(exc).__name__},
            )
        finally:
            disconnect_audit = asyncio.create_task(
                self._audit.append(
                    action="napcat.connection",
                    actor_id=actor_id,
                    outcome="disconnected",
                    details={"self_id": self_id},
                )
            )
            try:
                await asyncio.shield(disconnect_audit)
            except asyncio.CancelledError:
                await disconnect_audit
                raise

    def _authentication_error(self, websocket: WebSocket, self_id: str | None) -> str | None:
        if not self._enabled:
            return "adapter_disabled"
        if self_id is None or _SELF_ID_PATTERN.fullmatch(self_id) is None:
            return "self_id_missing_or_invalid"
        supplied = self._supplied_token(websocket)
        if supplied is None or self._access_token is None:
            return "token_missing"
        if not hmac.compare_digest(supplied, self._access_token):
            return "token_invalid"
        return None

    @staticmethod
    def _supplied_token(websocket: WebSocket) -> str | None:
        authorization = websocket.headers.get("authorization")
        if authorization is not None:
            scheme, separator, value = authorization.partition(" ")
            if separator and scheme.lower() == "bearer" and value:
                return value
            return None
        return websocket.query_params.get("access_token")

    async def _handle_frame_guarded(
        self,
        frame: dict[str, Any],
        connection: NapCatConnection,
        *,
        self_id: str,
    ) -> None:
        try:
            await self._handle_frame(frame, connection, self_id=self_id)
        except (ValidationError, ValueError) as exc:
            await self._audit.append(
                action="napcat.frame",
                actor_id=f"napcat:{self_id}",
                outcome="rejected",
                details={"reason_code": "schema_invalid", "error_code": type(exc).__name__},
            )
        except Exception as exc:
            await self._audit.append(
                action="napcat.frame",
                actor_id=f"napcat:{self_id}",
                outcome="failure",
                details={"error_code": type(exc).__name__},
            )

    async def _handle_frame(
        self,
        frame: dict[str, Any],
        connection: NapCatConnection,
        *,
        self_id: str,
    ) -> None:
        post_type = frame.get("post_type")
        if post_type == "meta_event":
            meta_event = OneBotMetaEvent.model_validate(frame)
            if meta_event.self_id != self_id:
                await self._audit_self_id_mismatch(self_id)
            return
        if post_type != "message":
            await self._audit.append(
                action="napcat.frame",
                actor_id=f"napcat:{self_id}",
                outcome="ignored",
                details={
                    "reason_code": "unsupported_post_type",
                    "post_type": post_type[:80] if isinstance(post_type, str) else "invalid",
                },
            )
            return

        message_event = OneBotMessageEvent.model_validate(frame)
        if message_event.self_id != self_id:
            await self._audit_self_id_mismatch(self_id)
            return
        if message_event.user_id == self_id:
            await self._audit.append(
                action="napcat.frame",
                actor_id=f"napcat:{self_id}",
                outcome="ignored",
                details={"reason_code": "self_message"},
            )
            return
        normalized = normalize_message(message_event)
        content = normalized.envelope.content
        text = content.get("text") if isinstance(content, dict) else None
        if not isinstance(text, str) or len(text) > self._max_message_chars:
            await self._audit.append(
                action="napcat.frame",
                actor_id=f"napcat:{self_id}",
                outcome="rejected",
                details={"reason_code": "message_too_large_or_invalid"},
            )
            return

        conversation_id = normalized.envelope.conversation_id
        if conversation_id is None:
            raise ValueError("NapCat messages require a conversation")
        utterance_turn = await self._runtime.begin_utterance_turn(
            conversation_id,
            platform="napcat",
        )
        assert utterance_turn is not None
        result = await self._runtime.handle_chat(normalized.envelope)
        if not await self._runtime.activate_utterance(utterance_turn, result):
            return
        if result.message is None:
            return
        messages = result.messages or [result.message]
        for index, message in enumerate(messages):
            if not await self._runtime.wait_for_utterance_unit(
                utterance_turn,
                result,
                unit_index=index,
            ):
                return
            if not await self._runtime.mark_utterance_unit_started(
                utterance_turn,
                result,
                unit_index=index,
            ):
                return
            reply = normalized.reply.model_copy(update={"message": message})
            delivered = await self._send_reply(
                reply,
                connection,
                event_id=result.event.event_id,
                conversation_id=conversation_id,
                taint_labels=result.event.taint_labels,
            )
            if not delivered:
                await self._runtime.cancel_utterance(
                    utterance_turn,
                    result,
                    reason_code="delivery_failed",
                )
                return
            await self._runtime.record_delivery(
                result,
                unit_index=index,
                platform="napcat",
            )

    async def _send_reply(
        self,
        reply: NapCatReplyArguments,
        connection: NapCatConnection,
        *,
        event_id: str,
        conversation_id: str | None,
        taint_labels: set[str],
    ) -> bool:
        if conversation_id is None:
            raise ValueError("NapCat replies require a conversation")
        resource_scope = f"{conversation_id}/event:{event_id}"
        grant = CapabilityGrant(
            actor_id="living-agent",
            capability=NAPCAT_REPLY_CAPABILITY,
            operations={"reply"},
            resource_scopes={resource_scope},
            conversation_id=conversation_id,
            one_time=True,
        )
        self._broker.add_grant(grant)
        decision = await self._broker.decide(
            CapabilityRequest(
                actor_id="living-agent",
                capability=NAPCAT_REPLY_CAPABILITY,
                operation="reply",
                resource_scope=resource_scope,
                arguments=reply.model_dump(),
                source_event_ids=[event_id],
                taint_labels=taint_labels,
                reason="Reply to one authenticated NapCat message in the same conversation.",
                conversation_id=conversation_id,
            )
        )
        if decision.outcome not in _ALLOW_OUTCOMES:
            self._broker.revoke_grant(grant)
            await self._audit.append(
                action="napcat.outbound",
                actor_id="living-agent",
                conversation_id=conversation_id,
                outcome="denied",
                details={"event_id": event_id, "reason_code": decision.reason_code},
            )
            return False

        action, params = onebot_reply_action(reply)
        try:
            raw_response = await connection.call_action(action, params)
            response = OneBotActionResponse.model_validate(raw_response)
        except NapCatActionTimeoutError:
            await self._audit_outbound_failure(
                conversation_id,
                event_id,
                action,
                "action_timeout",
            )
            return False
        except (NapCatConnectionError, ValidationError):
            await self._audit_outbound_failure(
                conversation_id,
                event_id,
                action,
                "invalid_or_disconnected_response",
            )
            return False

        if response.status != "ok" or response.retcode != 0:
            await self._audit_outbound_failure(
                conversation_id,
                event_id,
                action,
                "napcat_action_failed",
                retcode=response.retcode,
            )
            return False
        message_id = response.data.get("message_id") if response.data is not None else None
        await self._audit.append(
            action="napcat.outbound",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="success",
            details={
                "event_id": event_id,
                "action": action,
                "message_id": str(message_id)[:64] if message_id is not None else None,
            },
        )
        return True

    async def _audit_self_id_mismatch(self, self_id: str) -> None:
        await self._audit.append(
            action="napcat.frame",
            actor_id=f"napcat:{self_id}",
            outcome="rejected",
            details={"reason_code": "self_id_mismatch"},
        )

    async def _audit_outbound_failure(
        self,
        conversation_id: str,
        event_id: str,
        action: str,
        error_code: str,
        *,
        retcode: int | None = None,
    ) -> None:
        await self._audit.append(
            action="napcat.outbound",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="failure",
            details={
                "event_id": event_id,
                "action": action,
                "error_code": error_code,
                "retcode": retcode,
            },
        )
