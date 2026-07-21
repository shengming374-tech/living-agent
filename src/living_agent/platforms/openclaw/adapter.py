"""Authenticated OpenClaw channel ingress with broker-authorized synthetic replies."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import NoReturn

from pydantic import SecretStr

from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.interaction.repository import DeliveryDisposition
from living_agent.models.capabilities import (
    CapabilityGrant,
    CapabilityRequest,
    DecisionOutcome,
)
from living_agent.models.conversation import ChatResult
from living_agent.platforms.openclaw.models import (
    OPENCLAW_REPLY_CAPABILITY,
    OpenClawBridgeRequest,
    OpenClawBridgeResponse,
    OpenClawDeliveryReceipt,
    OpenClawDeliveryResponse,
    normalize_openclaw_message,
)
from living_agent.runtime.runtime import AgentRuntime

_ALLOW_OUTCOMES = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}


class OpenClawBridgeAuthError(PermissionError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class OpenClawBridgePolicyError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class OpenClawBridgeConflictError(RuntimeError):
    pass


@dataclass
class _IssuedUtterance:
    result: ChatResult
    channel_id: str
    account_id: str
    conversation_id: str
    delivered_indices: set[int] = field(default_factory=set)


class OpenClawBridgeAdapter:
    def __init__(
        self,
        *,
        enabled: bool,
        access_token: SecretStr | None,
        allowed_channels: list[str],
        allowed_account_ids: list[str],
        max_message_chars: int,
        idempotency_entries: int,
        runtime: AgentRuntime,
        broker: CapabilityBroker,
        audit: AuditService,
    ) -> None:
        self._enabled = enabled
        self._access_token = access_token.get_secret_value() if access_token is not None else None
        self._allowed_channels = frozenset(allowed_channels)
        self._allowed_account_ids = frozenset(allowed_account_ids)
        self._max_message_chars = max_message_chars
        self._idempotency_entries = idempotency_entries
        self._runtime = runtime
        self._broker = broker
        self._audit = audit
        self._cache_lock = asyncio.Lock()
        self._completed: OrderedDict[tuple[str, str, str], tuple[str, OpenClawBridgeResponse]] = (
            OrderedDict()
        )
        self._key_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._key_lock_users: dict[tuple[str, str, str], int] = {}
        self._issued_utterances: OrderedDict[str, _IssuedUtterance] = OrderedDict()

    async def authenticate(self, authorization: str | None) -> None:
        reason_code = self._authentication_error(authorization)
        if reason_code is None:
            return
        await self._audit.append(
            action="openclaw.bridge_auth",
            actor_id=None,
            outcome="rejected",
            details={"reason_code": reason_code},
        )
        raise OpenClawBridgeAuthError(reason_code)

    async def handle(self, request: OpenClawBridgeRequest) -> OpenClawBridgeResponse:
        try:
            self._validate_policy(request)
        except OpenClawBridgePolicyError as exc:
            await self._audit.append(
                action="openclaw.bridge_policy",
                actor_id=None,
                outcome="rejected",
                details={
                    "reason_code": exc.reason_code,
                    "channel_id": request.channel_id,
                    "account_id": request.account_id,
                    "message_id": request.message_id,
                },
            )
            raise
        key = (request.channel_id, request.account_id, request.message_id)
        fingerprint = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        key_lock = await self._retain_key_lock(key)
        try:
            async with key_lock:
                cached = await self._cached(key, fingerprint)
                if cached is not None:
                    return cached
                response = await self._handle_once(request)
                await self._remember(key, fingerprint, response)
                return response
        finally:
            await self._release_key_lock(key, key_lock)

    async def record_delivery(
        self,
        receipt: OpenClawDeliveryReceipt,
    ) -> OpenClawDeliveryResponse:
        async with self._cache_lock:
            issued = self._issued_utterances.get(receipt.utterance_session_id)
            stored = await self._runtime.utterance_session(receipt.utterance_session_id)
            if stored is None:
                await self._reject_delivery(receipt, "utterance_session_not_found")

            if issued is not None:
                if (
                    receipt.channel_id != issued.channel_id
                    or receipt.account_id != issued.account_id
                    or receipt.conversation_id != issued.conversation_id
                ):
                    await self._reject_delivery(receipt, "delivery_scope_mismatch")
            expected_conversation = (
                f"openclaw:{receipt.channel_id}:{receipt.account_id}:direct:"
                f"{receipt.conversation_id}"
            )
            if (
                stored.platform != "openclaw"
                or stored.conversation_id != expected_conversation
            ):
                await self._reject_delivery(receipt, "delivery_scope_mismatch")
            if receipt.unit_index >= len(stored.session.units):
                await self._reject_delivery(receipt, "delivery_unit_not_issued")
            if receipt.unit_index < stored.session.sent_count:
                return OpenClawDeliveryResponse(reason_code="delivery_already_recorded")
            if stored.session.state == "cancelled":
                await self._reject_delivery(receipt, "utterance_interrupted")
            if not await self._runtime.utterance_is_current(
                conversation_id=stored.conversation_id,
                platform="openclaw",
                session_id=stored.session.session_id,
            ):
                await self._reject_delivery(receipt, "utterance_interrupted")
            if receipt.unit_index != stored.session.sent_count:
                await self._reject_delivery(receipt, "delivery_out_of_order")
            delivery = await self._runtime.record_persisted_utterance_delivery(
                session_id=receipt.utterance_session_id,
                unit_index=receipt.unit_index,
                platform="openclaw",
                conversation_id=stored.conversation_id,
                recovered_after_restart=issued is None,
            )
            if delivery.disposition is DeliveryDisposition.RECORDED:
                if issued is not None:
                    issued.delivered_indices.add(receipt.unit_index)
                    self._issued_utterances.move_to_end(receipt.utterance_session_id)
                return OpenClawDeliveryResponse(reason_code="delivery_recorded")
            if delivery.disposition is DeliveryDisposition.ALREADY_RECORDED:
                return OpenClawDeliveryResponse(reason_code="delivery_already_recorded")
            reasons = {
                DeliveryDisposition.OUT_OF_ORDER: "delivery_out_of_order",
                DeliveryDisposition.INTERRUPTED: "utterance_interrupted",
                DeliveryDisposition.UNIT_NOT_ISSUED: "delivery_unit_not_issued",
                DeliveryDisposition.SCOPE_MISMATCH: "delivery_scope_mismatch",
                DeliveryDisposition.SESSION_NOT_FOUND: "utterance_session_not_found",
            }
            await self._reject_delivery(receipt, reasons[delivery.disposition])

    async def _reject_delivery(
        self,
        receipt: OpenClawDeliveryReceipt,
        reason_code: str,
    ) -> NoReturn:
        await self._audit.append(
            action="openclaw.delivery",
            actor_id=None,
            outcome="rejected",
            details={
                "reason_code": reason_code,
                "channel_id": receipt.channel_id,
                "account_id": receipt.account_id,
                "utterance_session_id": receipt.utterance_session_id,
                "unit_index": receipt.unit_index,
            },
        )
        raise OpenClawBridgePolicyError(reason_code)

    def _authentication_error(self, authorization: str | None) -> str | None:
        if not self._enabled:
            return "bridge_disabled"
        if self._access_token is None:
            return "bridge_token_unconfigured"
        if authorization is None:
            return "token_missing"
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not value:
            return "authorization_invalid"
        if not hmac.compare_digest(value, self._access_token):
            return "token_invalid"
        return None

    def _validate_policy(self, request: OpenClawBridgeRequest) -> None:
        if request.channel_id not in self._allowed_channels:
            raise OpenClawBridgePolicyError("channel_not_allowed")
        if self._allowed_account_ids and request.account_id not in self._allowed_account_ids:
            raise OpenClawBridgePolicyError("account_not_allowed")
        if request.is_group:
            raise OpenClawBridgePolicyError("group_chat_not_supported")
        if len(request.content) > self._max_message_chars:
            raise OpenClawBridgePolicyError("message_too_large")

    async def _handle_once(self, request: OpenClawBridgeRequest) -> OpenClawBridgeResponse:
        normalized = normalize_openclaw_message(request)
        utterance_turn = await self._runtime.begin_utterance_turn(
            normalized.envelope.conversation_id,
            platform="openclaw",
        )
        assert utterance_turn is not None
        result = await self._runtime.handle_chat(normalized.envelope)
        if result.message is None:
            await self._runtime.activate_utterance(utterance_turn, result)
            return OpenClawBridgeResponse(
                event_id=result.event.event_id,
                turn=result.turn,
                message=None,
                messages=[],
                unit_delays_ms=[],
                reason_code="runtime_observed",
            )

        reply_messages = result.messages or [result.message]
        reply = normalized.reply.model_copy(
            update={"message": reply_messages[0], "messages": reply_messages}
        )
        conversation_id = result.event.conversation_id
        if conversation_id is None:
            raise OpenClawBridgePolicyError("conversation_missing")
        resource_scope = f"{conversation_id}/event:{result.event.event_id}"
        grant = CapabilityGrant(
            actor_id="living-agent",
            capability=OPENCLAW_REPLY_CAPABILITY,
            operations={"reply"},
            resource_scopes={resource_scope},
            conversation_id=conversation_id,
            one_time=True,
        )
        self._broker.add_grant(grant)
        decision = await self._broker.decide(
            CapabilityRequest(
                actor_id="living-agent",
                capability=OPENCLAW_REPLY_CAPABILITY,
                operation="reply",
                resource_scope=resource_scope,
                arguments=reply.model_dump(),
                source_event_ids=[result.event.event_id],
                taint_labels=result.event.taint_labels,
                reason="Return one synthetic reply to the same OpenClaw channel event.",
                conversation_id=conversation_id,
            )
        )
        if decision.outcome not in _ALLOW_OUTCOMES:
            self._broker.revoke_grant(grant)
            await self._audit.append(
                action="openclaw.reply_delegated",
                actor_id="living-agent",
                conversation_id=conversation_id,
                outcome="denied",
                details={
                    "event_id": result.event.event_id,
                    "reason_code": decision.reason_code,
                },
            )
            return OpenClawBridgeResponse(
                event_id=result.event.event_id,
                turn=result.turn,
                message=None,
                messages=[],
                unit_delays_ms=[],
                reason_code=decision.reason_code,
            )

        if not await self._runtime.activate_utterance(utterance_turn, result):
            return OpenClawBridgeResponse(
                event_id=result.event.event_id,
                turn=result.turn,
                message=None,
                messages=[],
                unit_delays_ms=[],
                reason_code="superseded_by_new_inbound",
            )
        await self._audit.append(
            action="openclaw.reply_delegated",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="authorized",
            details={
                "event_id": result.event.event_id,
                "channel_id": request.channel_id,
                "account_id": request.account_id,
                "source_message_id": request.message_id,
                "unit_count": len(reply_messages),
            },
        )
        utterance_session_id = result.utterance.session_id if result.utterance is not None else None
        if utterance_session_id is not None:
            async with self._cache_lock:
                self._issued_utterances[utterance_session_id] = _IssuedUtterance(
                    result=result,
                    channel_id=request.channel_id,
                    account_id=request.account_id,
                    conversation_id=request.conversation_id,
                )
                self._issued_utterances.move_to_end(utterance_session_id)
                while len(self._issued_utterances) > self._idempotency_entries:
                    self._issued_utterances.popitem(last=False)
        return OpenClawBridgeResponse(
            event_id=result.event.event_id,
            turn=result.turn,
            message=reply_messages[0],
            messages=reply_messages,
            unit_delays_ms=self._runtime.utterance_delays_ms(result),
            utterance_session_id=utterance_session_id,
            reason_code="reply_authorized",
        )

    async def _retain_key_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        async with self._cache_lock:
            key_lock = self._key_locks.setdefault(key, asyncio.Lock())
            self._key_lock_users[key] = self._key_lock_users.get(key, 0) + 1
            return key_lock

    async def _release_key_lock(
        self,
        key: tuple[str, str, str],
        key_lock: asyncio.Lock,
    ) -> None:
        async with self._cache_lock:
            users = self._key_lock_users.get(key, 0)
            if users > 1:
                self._key_lock_users[key] = users - 1
                return
            self._key_lock_users.pop(key, None)
            if self._key_locks.get(key) is key_lock:
                self._key_locks.pop(key, None)

    async def _cached(
        self,
        key: tuple[str, str, str],
        fingerprint: str,
    ) -> OpenClawBridgeResponse | None:
        async with self._cache_lock:
            cached = self._completed.get(key)
            if cached is None:
                return None
            cached_fingerprint, response = cached
            if cached_fingerprint != fingerprint:
                raise OpenClawBridgeConflictError(
                    "message id was reused with different OpenClaw content"
                )
            self._completed.move_to_end(key)
            return response.model_copy(
                update={
                    "message": None,
                    "messages": [],
                    "unit_delays_ms": [],
                    "utterance_session_id": None,
                    "reason_code": "idempotent_replay",
                }
            )

    async def _remember(
        self,
        key: tuple[str, str, str],
        fingerprint: str,
        response: OpenClawBridgeResponse,
    ) -> None:
        async with self._cache_lock:
            self._completed[key] = (fingerprint, response)
            self._completed.move_to_end(key)
            while len(self._completed) > self._idempotency_entries:
                self._completed.popitem(last=False)
