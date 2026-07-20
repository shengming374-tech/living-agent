"""FastAPI reverse-WebSocket endpoint for NapCat OneBot 11 clients."""

from fastapi import APIRouter, WebSocket

from living_agent.platforms.napcat.adapter import NapCatAdapter

router = APIRouter(prefix="/v1/adapters/napcat", tags=["napcat"])


@router.websocket("/ws")
async def napcat_reverse_websocket(websocket: WebSocket) -> None:
    adapter: NapCatAdapter = websocket.app.state.napcat_adapter
    await adapter.serve(websocket)
