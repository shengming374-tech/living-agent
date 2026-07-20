"""Authenticated HTTP contract consumed by the OpenClaw bridge plugin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from living_agent.platforms.openclaw.adapter import (
    OpenClawBridgeAdapter,
    OpenClawBridgeAuthError,
    OpenClawBridgeConflictError,
    OpenClawBridgePolicyError,
)
from living_agent.platforms.openclaw.models import (
    OpenClawBridgeRequest,
    OpenClawBridgeResponse,
    OpenClawDeliveryReceipt,
    OpenClawDeliveryResponse,
)

router = APIRouter(prefix="/v1/adapters/openclaw", tags=["openclaw"])


@router.post("/messages", response_model=OpenClawBridgeResponse)
async def openclaw_message(
    payload: OpenClawBridgeRequest,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> OpenClawBridgeResponse:
    adapter: OpenClawBridgeAdapter = request.app.state.openclaw_bridge_adapter
    try:
        await adapter.authenticate(authorization)
        return await adapter.handle(payload)
    except OpenClawBridgeAuthError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.reason_code in {"bridge_disabled", "bridge_token_unconfigured"}
            else status.HTTP_401_UNAUTHORIZED
            if exc.reason_code == "token_missing"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=exc.reason_code) from exc
    except OpenClawBridgePolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.reason_code,
        ) from exc
    except OpenClawBridgeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OpenClaw message id conflict",
        ) from exc


@router.post("/deliveries", response_model=OpenClawDeliveryResponse)
async def openclaw_delivery(
    payload: OpenClawDeliveryReceipt,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> OpenClawDeliveryResponse:
    adapter: OpenClawBridgeAdapter = request.app.state.openclaw_bridge_adapter
    try:
        await adapter.authenticate(authorization)
        return await adapter.record_delivery(payload)
    except OpenClawBridgeAuthError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.reason_code in {"bridge_disabled", "bridge_token_unconfigured"}
            else status.HTTP_401_UNAUTHORIZED
            if exc.reason_code == "token_missing"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=exc.reason_code) from exc
    except OpenClawBridgePolicyError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.reason_code) from exc
