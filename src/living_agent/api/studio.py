"""Bundled Control Studio assets with restrictive browser headers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse, Response

router = APIRouter(include_in_schema=False)
_STUDIO_ROOT = Path(__file__).resolve().parents[1] / "studio"
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)


def _asset(name: str) -> FileResponse:
    response = FileResponse(_STUDIO_ROOT / name)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/")
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/studio", status_code=307)


@router.get("/studio")
async def control_studio() -> FileResponse:
    return _asset("index.html")


@router.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/studio/{asset_name}")
async def studio_asset(asset_name: Literal["app.js", "styles.css"]) -> FileResponse:
    return _asset(asset_name)
