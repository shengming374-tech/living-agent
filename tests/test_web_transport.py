"""TCP address binding and TLS identity regressions without external networking."""

import socket
import ssl
from pathlib import Path
from typing import Any

import httpcore2
import httpx2
import pytest

from living_agent.execution.web_transport import PINNED_ADDRESSES_EXTENSION, PinnedWebTransport
from living_agent.execution.work import WorkOperationError, WorkTaskExecutor

PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "1.1.1.1"


class RecordingStream(httpcore2.AsyncMockStream):
    def __init__(self, body: bytes, host: str, port: int, *, actual_peer: str | None = None):
        super().__init__([body])
        self.host, self.port = host, port
        self.actual_peer = actual_peer or host
        self.sent: list[bytes] = []
        self.tls_hostname: str | None = None
        self.verify_mode = None
        self.check_hostname = None

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:  # noqa: ASYNC109
        self.sent.append(buffer)

    async def start_tls(
        self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> httpcore2.AsyncNetworkStream:
        self.tls_hostname = server_hostname
        self.verify_mode = ssl_context.verify_mode
        self.check_hostname = ssl_context.check_hostname
        return self

    def get_extra_info(self, info: str) -> Any:
        if info == "server_addr":
            return self.actual_peer, self.port
        return super().get_extra_info(info)


class RecordingBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, responses: list[bytes], *, actual_peer: str | None = None):
        self.responses = responses
        self.actual_peer = actual_peer
        self.streams: list[RecordingStream] = []
        self.hosts: list[str] = []

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None, socket_options: Any = None,
    ) -> httpcore2.AsyncNetworkStream:
        self.hosts.append(host)
        stream = RecordingStream(self.responses.pop(0), host, port, actual_peer=self.actual_peer)
        self.streams.append(stream)
        return stream


async def test_validated_ip_is_dialled_once_while_host_and_tls_use_original_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions: list[str] = []

    def rebinding_dns(host: str, port: int, *args: Any) -> list[tuple]:
        assert host == "rebind.example"
        resolutions.append(host)
        address = PUBLIC_IP if len(resolutions) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_dns)
    backend = RecordingBackend([
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 6\r\n\r\nPUBLIC",
    ])
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        worker = WorkTaskExecutor(
            broker=None, audit=None, life=None, workspace_root=tmp_path, http_client=client,
        )
        url, _, body = await worker._fetch_bytes("https://rebind.example/project")
    assert url == "https://rebind.example/project"
    assert body == b"PUBLIC"
    assert resolutions == ["rebind.example"]
    assert backend.hosts == [PUBLIC_IP]
    stream = backend.streams[0]
    assert b"Host: rebind.example\r\n" in b"".join(stream.sent)
    assert stream.tls_hostname == "rebind.example"
    assert stream.verify_mode == ssl.CERT_REQUIRED
    assert stream.check_hostname is True
    assert stream._closed is True


async def test_redirect_resolves_and_pins_the_next_origin_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: list[str] = []

    def dns(host: str, port: int, *args: Any) -> list[tuple]:
        resolved.append(host)
        address = PUBLIC_IP if host == "first.example" else SECOND_PUBLIC_IP
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    backend = RecordingBackend([
        b"HTTP/1.1 302 Found\r\nLocation: https://second.example/result\r\n"
        b"Content-Length: 0\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK",
    ])
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        worker = WorkTaskExecutor(
            broker=None, audit=None, life=None, workspace_root=tmp_path, http_client=client,
        )
        url, _, body = await worker._fetch_bytes("https://first.example/start")
    assert url == "https://second.example/result"
    assert body == b"OK"
    assert resolved == ["first.example", "second.example"]
    assert backend.hosts == [PUBLIC_IP, SECOND_PUBLIC_IP]
    assert [stream.tls_hostname for stream in backend.streams] == [
        "first.example", "second.example",
    ]
    assert all(stream._closed for stream in backend.streams)


async def test_verified_connection_peer_must_equal_the_pinned_ip() -> None:
    backend = RecordingBackend([b""], actual_peer="127.0.0.1")
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        with pytest.raises(httpx2.ConnectError, match="differs from approved"):
            await client.get("https://example.com/", extensions={
                PINNED_ADDRESSES_EXTENSION: (PUBLIC_IP,),
            })
    assert backend.streams[0]._closed is True
    assert backend.streams[0].tls_hostname is None


@pytest.mark.parametrize("addresses", [(), ("127.0.0.1",), ("100.64.0.1",), ("224.0.0.1",)])
async def test_missing_or_non_public_pins_fail_before_connection(addresses: tuple[str]) -> None:
    backend = RecordingBackend([])
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        with pytest.raises(httpx2.ConnectError):
            await client.get("https://example.com/", extensions={
                PINNED_ADDRESSES_EXTENSION: addresses,
            })
    assert backend.hosts == []


async def test_redirect_to_private_origin_is_blocked_before_second_connection(
    tmp_path: Path,
) -> None:
    backend = RecordingBackend([
        b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n",
    ])
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        worker = WorkTaskExecutor(
            broker=None, audit=None, life=None, workspace_root=tmp_path, http_client=client,
        )
        with pytest.raises(WorkOperationError, match="web_private_address_denied"):
            await worker._fetch_bytes(f"https://{PUBLIC_IP}/start")
    assert backend.hosts == [PUBLIC_IP]


async def test_injected_live_transport_cannot_bypass_address_binding(tmp_path: Path) -> None:
    async with httpx2.AsyncClient(trust_env=False) as client:
        worker = WorkTaskExecutor(
            broker=None, audit=None, life=None, workspace_root=tmp_path, http_client=client,
        )
        with pytest.raises(WorkOperationError, match="web_unpinned_transport_denied"):
            await worker._fetch_bytes(f"https://{PUBLIC_IP}/private")
    worker = WorkTaskExecutor(broker=None, audit=None, life=None, workspace_root=tmp_path)
    try:
        assert isinstance(worker._client._transport, PinnedWebTransport)
    finally:
        await worker.close()


async def test_tls_verification_failure_is_propagated_without_ip_fallback() -> None:
    class RejectedCertificateStream(RecordingStream):
        async def start_tls(
            self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
            timeout: float | None = None,  # noqa: ASYNC109
        ) -> httpcore2.AsyncNetworkStream:
            assert server_hostname == "certificate.example"
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            assert ssl_context.check_hostname is True
            raise httpcore2.ConnectError("certificate verification failed")

    class RejectedCertificateBackend(RecordingBackend):
        async def connect_tcp(
            self, host: str, port: int, timeout: float | None = None,  # noqa: ASYNC109
            local_address: str | None = None, socket_options: Any = None,
        ) -> httpcore2.AsyncNetworkStream:
            self.hosts.append(host)
            return RejectedCertificateStream(b"", host, port)

    backend = RejectedCertificateBackend([])
    async with httpx2.AsyncClient(transport=PinnedWebTransport(backend=backend)) as client:
        with pytest.raises(httpx2.ConnectError, match="certificate verification failed"):
            await client.get("https://certificate.example/", extensions={
                PINNED_ADDRESSES_EXTENSION: (PUBLIC_IP,),
            })
    assert backend.hosts == [PUBLIC_IP]
