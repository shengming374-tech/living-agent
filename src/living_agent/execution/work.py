"""Audited host executor for bounded workspace, web, and daily-plan work."""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import os
import socket
import tempfile
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

import httpx2
from pydantic import ValidationError

from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.execution.contracts import (
    PlannedAction,
    TaskEvidence,
    TaskStepResult,
    TaskStepStatus,
)
from living_agent.execution.work_contracts import (
    DailyPlanReadArguments,
    DailyPlanUpdateArguments,
    DailyPlanWriteArguments,
    WebFetchArguments,
    WebSearchArguments,
    WorkspaceListArguments,
    WorkspaceReadArguments,
    WorkspaceSearchArguments,
    WorkspaceWriteArguments,
    is_work_write_handler,
    normalize_web_url,
)
from living_agent.life.repository import (
    LifeConflictError,
    LifeNotFoundError,
    LifeStateError,
)
from living_agent.life.service import LifeService
from living_agent.models.capabilities import CapabilityGrant, DecisionOutcome
from living_agent.models.life import DailyPlanUpsert, PlanItemStatusUpdate
from living_agent.models.tasks import TaskContract

_ALLOWED_DECISIONS = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_READ_ONLY,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}
_READABLE_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xhtml+xml",
    "application/xml",
)
_SENSITIVE_PARTS = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".azure",
        ".docker",
        ".gcloud",
        ".gnupg",
        ".kube",
        "credentials",
    }
)
_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
        "known_hosts",
        ".netrc",
        ".npmrc",
        ".pypirc",
    }
)
_SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


class WorkOperationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if lowered == "title":
            self._in_title = True
        if lowered in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._in_title:
            self.title = f"{self.title} {normalized}".strip()
        else:
            self._parts.append(normalized)

    def text(self) -> str:
        lines = []
        for raw_line in " ".join(self._parts).splitlines():
            normalized = " ".join(raw_line.split())
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "result__a" in classes or "result-link" in classes:
            self._href = values.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        title = " ".join("".join(self._text).split())
        if title:
            self.results.append({"title": html.unescape(title), "url": self._href})
        self._href = None
        self._text = []


class WorkTaskExecutor:
    def __init__(
        self,
        *,
        broker: CapabilityBroker,
        audit: AuditService,
        life: LifeService,
        workspace_root: Path,
        http_client: httpx2.AsyncClient | None = None,
        web_search_endpoint: str = "https://html.duckduckgo.com/html/",
        web_allowed_hosts: Iterable[str] = (),
        allow_insecure_http: bool = False,
        max_file_bytes: int = 1_048_576,
        max_web_bytes: int = 1_048_576,
        web_timeout_seconds: float = 15.0,
    ) -> None:
        root = workspace_root.expanduser().resolve()
        if not root.is_dir():
            raise ValueError("work workspace root must be an existing directory")
        self._broker = broker
        self._audit = audit
        self._life = life
        self._workspace_root = root
        self._search_endpoint = normalize_web_url(web_search_endpoint)
        self._allowed_hosts = {item.strip().rstrip(".").casefold() for item in web_allowed_hosts}
        self._allow_insecure_http = allow_insecure_http
        self._max_file_bytes = max_file_bytes
        self._max_web_bytes = max_web_bytes
        self._client = http_client or httpx2.AsyncClient(
            timeout=web_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "LivingAgent/0.2 (+bounded-web-reader)"},
        )
        self._owns_client = http_client is None

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def execute(
        self,
        *,
        task: TaskContract,
        action: PlannedAction,
        confirmed_by: str | None,
    ) -> TaskStepResult:
        request = action.capability_request
        grant = CapabilityGrant(
            actor_id=request.actor_id,
            capability=request.capability,
            operations={request.operation},
            resource_scopes={request.resource_scope},
            conversation_id=request.conversation_id,
            one_time=True,
        )
        self._broker.add_grant(grant)
        decision = await self._broker.decide(request, confirmed_by=confirmed_by)
        if decision.outcome is DecisionOutcome.ASK_OWNER:
            self._broker.revoke_grant(grant)
            return TaskStepResult(
                step_id="pending",
                status=TaskStepStatus.WAITING_CONFIRMATION,
                confirmation_request_id=request.request_id,
            )
        if decision.outcome not in _ALLOWED_DECISIONS:
            self._broker.revoke_grant(grant)
            return self._failure(decision.reason_code)
        try:
            output, evidence = await self._dispatch(action)
        except (ValidationError, ValueError):
            return self._failure("work_arguments_invalid")
        except WorkOperationError as exc:
            return self._failure(exc.code)
        except (OSError, httpx2.HTTPError, UnicodeError):
            return self._failure("work_operation_failed")

        tool_audit = await self._audit.append(
            action="tool.called",
            actor_id=task.requester_id,
            conversation_id=request.conversation_id,
            outcome="verified",
            details={
                "capability": request.capability,
                "operation": request.operation,
                "resource_scope": request.resource_scope,
                "task_id": task.task_id,
                "evidence_kind": evidence.kind,
            },
        )
        evidence = evidence.model_copy(
            update={"data": {**evidence.data, "tool_audit_id": tool_audit.audit_id}}
        )
        return TaskStepResult(
            step_id="completed",
            status=TaskStepStatus.COMPLETED,
            output=output,
            evidence=[evidence],
        )

    async def _dispatch(self, action: PlannedAction) -> tuple[dict[str, Any], TaskEvidence]:
        handler = action.handler
        arguments = action.capability_request.arguments
        if handler == "workspace_read":
            return await asyncio.to_thread(
                self._read_file, WorkspaceReadArguments.model_validate(arguments)
            )
        if handler == "workspace_list":
            return await asyncio.to_thread(
                self._list_directory, WorkspaceListArguments.model_validate(arguments)
            )
        if handler == "workspace_search":
            return await asyncio.to_thread(
                self._search_workspace, WorkspaceSearchArguments.model_validate(arguments)
            )
        if handler == "workspace_write":
            return await asyncio.to_thread(
                self._write_file, WorkspaceWriteArguments.model_validate(arguments)
            )
        if handler == "web_fetch":
            return await self._fetch_page(WebFetchArguments.model_validate(arguments))
        if handler == "web_search":
            return await self._search_web(WebSearchArguments.model_validate(arguments))
        if handler == "daily_plan_read":
            return await self._read_daily_plan(DailyPlanReadArguments.model_validate(arguments))
        if handler == "daily_plan_write":
            return await self._write_daily_plan(
                DailyPlanWriteArguments.model_validate(arguments),
                actor_id=action.capability_request.actor_id,
            )
        if handler == "daily_plan_update":
            return await self._update_daily_plan(
                DailyPlanUpdateArguments.model_validate(arguments),
                actor_id=action.capability_request.actor_id,
            )
        raise WorkOperationError("work_handler_unknown")

    def _read_file(self, arguments: WorkspaceReadArguments) -> tuple[dict[str, Any], TaskEvidence]:
        target = self._resolve_workspace_path(arguments.path, must_exist=True)
        if not target.is_file():
            raise WorkOperationError("workspace_not_file")
        size = target.stat().st_size
        if size > self._max_file_bytes:
            raise WorkOperationError("workspace_file_too_large")
        raw = target.read_bytes()
        if b"\x00" in raw[:8192]:
            raise WorkOperationError("workspace_binary_file_denied")
        text = raw.decode("utf-8")
        relative = target.relative_to(self._workspace_root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        output = {
            "kind": "workspace_file",
            "path": relative,
            "text": text[: arguments.max_chars],
            "truncated": len(text) > arguments.max_chars,
            "bytes": len(raw),
            "sha256": digest,
            "taint_labels": ["untrusted_document"],
        }
        evidence = TaskEvidence(
            kind="file_snapshot",
            source="host_workspace",
            data={"path": relative, "bytes": len(raw), "sha256": digest},
        )
        return output, evidence

    def _list_directory(
        self, arguments: WorkspaceListArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        target = self._resolve_workspace_path(arguments.path, must_exist=True)
        if not target.is_dir():
            raise WorkOperationError("workspace_not_directory")
        iterator = target.rglob("*") if arguments.recursive else target.iterdir()
        entries = []
        for item in sorted(iterator, key=lambda path: path.as_posix().casefold()):
            if self._is_sensitive(item) or not self._inside_workspace(item):
                continue
            relative = item.relative_to(self._workspace_root).as_posix()
            entries.append(
                {
                    "path": relative,
                    "type": "symlink"
                    if item.is_symlink()
                    else "directory"
                    if item.is_dir()
                    else "file",
                    "bytes": item.stat().st_size if item.is_file() else None,
                }
            )
            if len(entries) >= arguments.max_entries:
                break
        relative_root = target.relative_to(self._workspace_root).as_posix() or "."
        output = {
            "kind": "workspace_listing",
            "path": relative_root,
            "entries": entries,
            "truncated": len(entries) >= arguments.max_entries,
            "taint_labels": ["untrusted_document"],
        }
        evidence = TaskEvidence(
            kind="directory_snapshot",
            source="host_workspace",
            data={"path": relative_root, "entry_count": len(entries)},
        )
        return output, evidence

    def _search_workspace(
        self, arguments: WorkspaceSearchArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        target = self._resolve_workspace_path(arguments.path, must_exist=True)
        candidates = [target] if target.is_file() else target.rglob("*")
        needle = arguments.query.casefold()
        matches: list[dict[str, Any]] = []
        scanned = 0
        for item in candidates:
            if scanned >= 1000 or len(matches) >= arguments.max_matches:
                break
            if not item.is_file() or item.is_symlink() or self._is_sensitive(item):
                continue
            if not self._inside_workspace(item) or item.stat().st_size > self._max_file_bytes:
                continue
            scanned += 1
            try:
                raw = item.read_bytes()
                if b"\x00" in raw[:8192]:
                    continue
                text = raw.decode("utf-8")
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if needle not in line.casefold():
                    continue
                matches.append(
                    {
                        "path": item.relative_to(self._workspace_root).as_posix(),
                        "line": line_number,
                        "text": line.strip()[:500],
                    }
                )
                if len(matches) >= arguments.max_matches:
                    break
        output = {
            "kind": "workspace_search",
            "query": arguments.query,
            "matches": matches,
            "files_scanned": scanned,
            "truncated": len(matches) >= arguments.max_matches,
            "taint_labels": ["untrusted_document"],
        }
        evidence = TaskEvidence(
            kind="workspace_search",
            source="host_workspace",
            data={
                "query_sha256": hashlib.sha256(arguments.query.encode()).hexdigest(),
                "files_scanned": scanned,
                "match_count": len(matches),
            },
        )
        return output, evidence

    def _write_file(
        self, arguments: WorkspaceWriteArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        target = self._resolve_workspace_path(arguments.path, must_exist=False)
        parent = target.parent.resolve(strict=True)
        if not parent.is_dir() or not self._inside_workspace(parent):
            raise WorkOperationError("workspace_parent_invalid")
        encoded = arguments.content.encode("utf-8")
        if len(encoded) > self._max_file_bytes:
            raise WorkOperationError("workspace_write_too_large")
        if target.exists() and not arguments.overwrite:
            raise WorkOperationError("workspace_file_exists")
        if arguments.overwrite:
            file_descriptor, temporary_name = tempfile.mkstemp(prefix=".living-agent-", dir=parent)
            try:
                with os.fdopen(file_descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, target)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        else:
            with target.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        digest = hashlib.sha256(encoded).hexdigest()
        relative = target.relative_to(self._workspace_root).as_posix()
        output = {
            "kind": "workspace_write",
            "path": relative,
            "bytes_written": len(encoded),
            "sha256": digest,
        }
        evidence = TaskEvidence(
            kind="file_commit",
            source="host_workspace",
            data={"path": relative, "bytes": len(encoded), "sha256": digest},
        )
        return output, evidence

    async def _fetch_page(
        self, arguments: WebFetchArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        final_url, content_type, raw = await self._fetch_bytes(arguments.url)
        text, title = self._decode_document(raw, content_type)
        digest = hashlib.sha256(raw).hexdigest()
        output = {
            "kind": "web_page",
            "url": final_url,
            "title": title,
            "text": text[: arguments.max_chars],
            "truncated": len(text) > arguments.max_chars,
            "bytes": len(raw),
            "sha256": digest,
            "taint_labels": ["untrusted_document"],
        }
        evidence = TaskEvidence(
            kind="remote_response",
            source="host_web_reader",
            data={
                "url": final_url,
                "content_type": content_type,
                "bytes": len(raw),
                "sha256": digest,
            },
        )
        return output, evidence

    async def _search_web(
        self, arguments: WebSearchArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        separator = "&" if urlsplit(self._search_endpoint).query else "?"
        search_url = f"{self._search_endpoint}{separator}q={quote_plus(arguments.query)}"
        final_url, content_type, raw = await self._fetch_bytes(search_url)
        if "html" not in content_type:
            raise WorkOperationError("web_search_response_invalid")
        parser = _SearchParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        results = []
        for result in parser.results:
            resolved = self._search_result_url(urljoin(final_url, result["url"]))
            try:
                normalized = normalize_web_url(resolved)
            except ValueError:
                continue
            results.append({"title": result["title"][:500], "url": normalized})
            if len(results) >= arguments.max_results:
                break
        output = {
            "kind": "web_search",
            "query": arguments.query,
            "results": results,
            "taint_labels": ["untrusted_tool_result"],
        }
        evidence = TaskEvidence(
            kind="remote_search_response",
            source="host_web_search",
            data={
                "query_sha256": hashlib.sha256(arguments.query.encode()).hexdigest(),
                "result_count": len(results),
            },
        )
        return output, evidence

    async def _read_daily_plan(
        self, arguments: DailyPlanReadArguments
    ) -> tuple[dict[str, Any], TaskEvidence]:
        try:
            plan = await self._life.get_plan(arguments.plan_date)
        except LifeNotFoundError:
            output: dict[str, Any] = {
                "kind": "daily_plan",
                "plan_date": arguments.plan_date.isoformat(),
                "found": False,
            }
            version = None
        else:
            output = {
                "kind": "daily_plan",
                "found": True,
                **plan.model_dump(mode="json"),
            }
            version = plan.version
        evidence = TaskEvidence(
            kind="database_read",
            source="life_repository",
            data={
                "plan_date": arguments.plan_date.isoformat(),
                "found": output["found"],
                "version": version,
            },
        )
        return output, evidence

    async def _write_daily_plan(
        self,
        arguments: DailyPlanWriteArguments,
        *,
        actor_id: str,
    ) -> tuple[dict[str, Any], TaskEvidence]:
        expected_version = arguments.expected_version
        existing = None
        try:
            existing = await self._life.get_plan(arguments.plan_date)
        except LifeNotFoundError:
            pass
        if expected_version is None and existing is not None:
            expected_version = existing.version
        items = list(arguments.items)
        intention = arguments.intention
        if arguments.mode == "append" and existing is not None:
            existing_titles = {item.title.casefold() for item in existing.items}
            items = [
                *existing.items,
                *(item for item in items if item.title.casefold() not in existing_titles),
            ]
            intention = existing.intention
        try:
            plan = await self._life.upsert_plan(
                arguments.plan_date,
                DailyPlanUpsert(
                    expected_version=expected_version,
                    intention=intention,
                    items=items,
                ),
                actor_id=actor_id,
            )
        except LifeConflictError as exc:
            raise WorkOperationError("daily_plan_conflict") from exc
        output = {
            "kind": "daily_plan_write",
            **plan.model_dump(mode="json"),
        }
        evidence = TaskEvidence(
            kind="database_commit",
            source="life_repository",
            data={
                "plan_id": plan.plan_id,
                "plan_date": plan.plan_date.isoformat(),
                "version": plan.version,
                "item_count": len(plan.items),
            },
        )
        return output, evidence

    async def _update_daily_plan(
        self,
        arguments: DailyPlanUpdateArguments,
        *,
        actor_id: str,
    ) -> tuple[dict[str, Any], TaskEvidence]:
        try:
            plan = await self._life.get_plan(arguments.plan_date)
        except LifeNotFoundError as exc:
            raise WorkOperationError("daily_plan_not_found") from exc
        needle = arguments.item_title.casefold()
        exact = [item for item in plan.items if item.title.casefold() == needle]
        matches = exact or [item for item in plan.items if needle in item.title.casefold()]
        if not matches:
            raise WorkOperationError("daily_plan_item_not_found")
        if len(matches) > 1:
            raise WorkOperationError("daily_plan_item_ambiguous")
        item = matches[0]
        try:
            updated = await self._life.transition_plan_item(
                arguments.plan_date,
                item.item_id,
                PlanItemStatusUpdate(
                    expected_version=plan.version,
                    status=arguments.status,
                ),
                actor_id=actor_id,
            )
        except (LifeConflictError, LifeNotFoundError, LifeStateError) as exc:
            raise WorkOperationError("daily_plan_conflict") from exc
        output = {
            "kind": "daily_plan_update",
            "plan_id": updated.plan_id,
            "plan_date": updated.plan_date.isoformat(),
            "item_id": item.item_id,
            "item_title": item.title,
            "status": arguments.status.value,
            "version": updated.version,
        }
        evidence = TaskEvidence(
            kind="database_commit",
            source="life_repository",
            data={
                "plan_id": updated.plan_id,
                "plan_date": updated.plan_date.isoformat(),
                "item_id": item.item_id,
                "status": arguments.status.value,
                "version": updated.version,
            },
        )
        return output, evidence

    async def _fetch_bytes(self, initial_url: str) -> tuple[str, str, bytes]:
        current = normalize_web_url(initial_url)
        for _redirect in range(4):
            await self._validate_remote_url(current)
            request = self._client.build_request("GET", current)
            response = await self._client.send(request, stream=True)
            try:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise WorkOperationError("web_redirect_invalid")
                    current = normalize_web_url(urljoin(current, location))
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    raise WorkOperationError("web_http_error")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if not any(content_type.startswith(item) for item in _READABLE_CONTENT_TYPES):
                    raise WorkOperationError("web_content_type_denied")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise WorkOperationError("web_response_invalid") from exc
                    if declared_size > self._max_web_bytes:
                        raise WorkOperationError("web_response_too_large")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_web_bytes:
                        raise WorkOperationError("web_response_too_large")
                    chunks.append(chunk)
                return current, content_type, b"".join(chunks)
            finally:
                await response.aclose()
        raise WorkOperationError("web_redirect_limit")

    async def _validate_remote_url(self, url: str) -> None:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        if parsed.scheme != "https" and not self._allow_insecure_http:
            raise WorkOperationError("web_insecure_url_denied")
        if self._allowed_hosts and hostname not in self._allowed_hosts:
            raise WorkOperationError("web_host_not_allowed")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise WorkOperationError("web_private_address_denied")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                records = await asyncio.to_thread(
                    socket.getaddrinfo,
                    hostname,
                    port,
                    socket.AF_UNSPEC,
                    socket.SOCK_STREAM,
                )
            except OSError as exc:
                raise WorkOperationError("web_dns_failed") from exc
            addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        else:
            addresses = {literal}
        if not addresses or any(not self._is_public_address(item) for item in addresses):
            raise WorkOperationError("web_private_address_denied")

    def _resolve_workspace_path(self, raw_path: str, *, must_exist: bool) -> Path:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            raise WorkOperationError("workspace_absolute_path_denied")
        unresolved = self._workspace_root / candidate
        try:
            target = unresolved.resolve(strict=must_exist)
        except FileNotFoundError as exc:
            raise WorkOperationError("workspace_path_not_found") from exc
        if not self._inside_workspace(target):
            raise WorkOperationError("workspace_path_escape_denied")
        if self._is_sensitive(target):
            raise WorkOperationError("workspace_sensitive_path_denied")
        return target

    def _inside_workspace(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._workspace_root)
        except (OSError, ValueError):
            return False
        return True

    def _is_sensitive(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self._workspace_root)
        except ValueError:
            return True
        parts = [part.casefold() for part in relative.parts]
        if any(part in _SENSITIVE_PARTS for part in parts):
            return True
        name = relative.name.casefold()
        return (
            name in _SENSITIVE_NAMES
            or name.startswith(".env")
            or Path(name).suffix in _SENSITIVE_SUFFIXES
        )

    @staticmethod
    def _decode_document(raw: bytes, content_type: str) -> tuple[str, str]:
        decoded = raw.decode("utf-8", errors="replace")
        if "html" not in content_type:
            return "\n".join(line.rstrip() for line in decoded.splitlines()).strip(), ""
        parser = _DocumentParser()
        parser.feed(decoded)
        return parser.text(), parser.title[:500]

    @staticmethod
    def _search_result_url(url: str) -> str:
        parsed = urlsplit(url)
        redirected = parse_qs(parsed.query).get("uddg")
        return redirected[0] if redirected else url

    @staticmethod
    def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    @staticmethod
    def _failure(code: str) -> TaskStepResult:
        return TaskStepResult(
            step_id="failed",
            status=TaskStepStatus.FAILED,
            errors=[code],
        )


def work_action_requires_confirmation(action: PlannedAction) -> bool:
    return is_work_write_handler(action.handler)
