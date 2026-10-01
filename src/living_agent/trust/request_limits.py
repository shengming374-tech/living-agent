"""Count actual API body bytes, including requests without Content-Length."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
                if declared < 0:
                    raise ValueError("negative length")
            except ValueError:
                response = JSONResponse(
                    status_code=400, content={"detail": "invalid_content_length"}
                )
                await response(scope, receive, send)
                return
            if declared > self._max_bytes:
                await self._reject(scope, receive, send)
                return
        size = 0

        async def bounded_receive() -> Message:
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self._max_bytes:
                    raise HTTPException(413, "request_body_too_large")
            return message

        await self._app(scope, bounded_receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(status_code=413, content={"detail": "request_body_too_large"})
        await response(scope, receive, send)
