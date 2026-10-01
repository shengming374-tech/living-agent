"""Bind validated public addresses to TCP while retaining HTTP Host and TLS identity.

将已校验公网 IP 绑定到 TCP 连接, 保留原域名 Host、SNI 和证书校验。
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import AsyncIterator, Iterable

import httpcore2
import httpx2
from httpx2._config import create_ssl_context
from httpx2._transports.default import map_httpcore_exceptions

PINNED_ADDRESSES_EXTENSION = "living_agent_public_addresses"


class PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    def __init__(
        self, *, hostname: str, port: int, addresses: tuple[str, ...],
        backend: httpcore2.AsyncNetworkBackend,
    ) -> None:
        self._hostname = hostname.rstrip(".").casefold()
        self._port = port
        self._addresses = addresses
        self._backend = backend

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if host.rstrip(".").casefold() != self._hostname or port != self._port:
            raise httpcore2.ConnectError("connection origin differs from validated origin")
        started = time.monotonic()
        failure: Exception = httpcore2.ConnectError("no approved public address")
        for address in self._addresses:
            remaining = None if timeout is None else timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise httpcore2.ConnectTimeout("approved address connection timed out")
            try:
                stream = await self._backend.connect_tcp(
                    address, port, timeout=remaining, local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                failure = exc
                continue
            peer = stream.get_extra_info("server_addr")
            try:
                actual_address = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
                actual_port = int(peer[1])
            except (IndexError, TypeError, ValueError):
                await stream.aclose()
                raise httpcore2.ConnectError("connected peer could not be verified") from None
            if actual_address != ipaddress.ip_address(address) or actual_port != port:
                await stream.aclose()
                raise httpcore2.ConnectError("connected peer differs from approved address")
            return stream
        raise failure

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None,  # noqa: ASYNC109
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise httpcore2.ConnectError("web requests cannot use Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedResponseStream(httpx2.AsyncByteStream):
    def __init__(self, response: httpcore2.Response, pool: httpcore2.AsyncConnectionPool) -> None:
        self._response = response
        self._pool = pool

    async def __aiter__(self) -> AsyncIterator[bytes]:
        with map_httpcore_exceptions():
            async for chunk in self._response.aiter_stream():
                yield chunk

    async def aclose(self) -> None:
        with map_httpcore_exceptions():
            try:
                await self._response.aclose()
            finally:
                await self._pool.aclose()


class PinnedWebTransport(httpx2.AsyncBaseTransport):
    """A separate pool per validated request prevents reuse across DNS snapshots."""

    def __init__(self, *, backend: httpcore2.AsyncNetworkBackend | None = None) -> None:
        self._backend = backend or httpcore2.AnyIOBackend()
        self._ssl_context = create_ssl_context(trust_env=False)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        supplied = request.extensions.get(PINNED_ADDRESSES_EXTENSION)
        if not isinstance(supplied, tuple) or not supplied:
            raise httpx2.ConnectError(
                "web request has no validated public addresses", request=request,
            )
        addresses: list[str] = []
        for value in supplied:
            if not isinstance(value, str):
                raise httpx2.ConnectError("invalid pinned address", request=request)
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                raise httpx2.ConnectError("invalid pinned address", request=request) from None
            if not address.is_global or address.is_multicast:
                raise httpx2.ConnectError("pinned address must be public", request=request)
            addresses.append(str(address))
        if request.url.scheme not in {"http", "https"}:
            raise httpx2.UnsupportedProtocol("unsupported web URL", request=request)
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        hostname = request.url.raw_host.decode("ascii")
        pool = httpcore2.AsyncConnectionPool(
            ssl_context=self._ssl_context,
            network_backend=PinnedNetworkBackend(
                hostname=hostname, port=port, addresses=tuple(addresses), backend=self._backend,
            ),
            max_connections=1, max_keepalive_connections=0,
        )
        # Keep the original URL: httpcore sends its Host and uses it for TLS SNI/verification.
        # / 原 URL 保留到 httpcore, 因此证书必须匹配原域名。
        extensions = dict(request.extensions)
        extensions.pop(PINNED_ADDRESSES_EXTENSION, None)
        extensions.pop("sni_hostname", None)
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        core_request = httpcore2.Request(
            method=request.method,
            url=httpcore2.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                              port=request.url.port, target=request.url.raw_path),
            headers=headers.raw, content=request.stream,
            extensions=extensions,
        )
        try:
            with map_httpcore_exceptions():
                response = await pool.handle_async_request(core_request)
        except BaseException:
            await pool.aclose()
            raise
        return httpx2.Response(
            status_code=response.status, headers=response.headers,
            stream=_PinnedResponseStream(response, pool), extensions=response.extensions,
        )
