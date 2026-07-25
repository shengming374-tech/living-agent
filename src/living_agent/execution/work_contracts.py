"""Typed contracts for host-owned workspace, web, and daily-plan work."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from living_agent.models.life import DailyPlanItemInput, PlanItemStatus

WORKSPACE_READ_CAPABILITY = "workspace.file.read"
WORKSPACE_LIST_CAPABILITY = "workspace.directory.list"
WORKSPACE_SEARCH_CAPABILITY = "workspace.text.search"
WORKSPACE_WRITE_CAPABILITY = "workspace.file.write"
WEB_FETCH_CAPABILITY = "web.page.read"
WEB_SEARCH_CAPABILITY = "web.search"
DAILY_PLAN_READ_CAPABILITY = "life.daily_plan.read"
DAILY_PLAN_WRITE_CAPABILITY = "life.daily_plan.write"
DAILY_PLAN_UPDATE_CAPABILITY = "life.daily_plan.update"

WORK_HANDLERS = frozenset(
    {
        "workspace_read",
        "workspace_list",
        "workspace_search",
        "workspace_write",
        "web_fetch",
        "web_search",
        "daily_plan_read",
        "daily_plan_write",
        "daily_plan_update",
        "shell_execute",
    }
)
WORK_WRITE_HANDLERS = frozenset(
    {"workspace_write", "daily_plan_write", "daily_plan_update", "shell_execute"}
)


class _WorkspacePathModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        if not normalized or "\x00" in normalized:
            raise ValueError("workspace path is invalid")
        return normalized


class WorkspaceReadArguments(_WorkspacePathModel):
    max_chars: int = Field(default=20_000, ge=1, le=100_000)


class WorkspaceListArguments(_WorkspacePathModel):
    recursive: bool = False
    max_entries: int = Field(default=200, ge=1, le=1000)


class WorkspaceSearchArguments(_WorkspacePathModel):
    query: str = Field(min_length=1, max_length=500)
    max_matches: int = Field(default=100, ge=1, le=500)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace search query cannot be empty")
        return normalized


class WorkspaceWriteArguments(_WorkspacePathModel):
    content: str = Field(min_length=1, max_length=200_000)
    overwrite: bool = True


class WebFetchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=2048)
    max_chars: int = Field(default=20_000, ge=1, le=100_000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return normalize_web_url(value)


class WebSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=8, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("web search query cannot be empty")
        return normalized


class DailyPlanReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date


class DailyPlanWriteArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    intention: str = Field(min_length=1, max_length=1000)
    items: list[DailyPlanItemInput] = Field(min_length=1, max_length=50)
    expected_version: int | None = Field(default=None, ge=1)
    mode: Literal["replace", "append"] = "replace"


class DailyPlanUpdateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    item_title: str = Field(min_length=1, max_length=300)
    status: PlanItemStatus


def workspace_scope(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized or "."
    return f"workspace/{normalized}"


def workspace_scope_matches(arguments: BaseModel, scope: str) -> bool:
    path = getattr(arguments, "path", None)
    return isinstance(path, str) and scope == workspace_scope(path)


def normalize_web_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("web URL must be an HTTP(S) URL without credentials")
    hostname = parsed.hostname.rstrip(".").casefold()
    if not hostname:
        raise ValueError("web URL hostname is invalid")
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (
        parsed.scheme.lower() == "http" and port == 80
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def web_fetch_scope(arguments: BaseModel, scope: str) -> bool:
    url = getattr(arguments, "url", None)
    return isinstance(url, str) and scope == f"url:{normalize_web_url(url)}"


def web_search_scope(query: str) -> str:
    digest = hashlib.sha256(query.strip().casefold().encode()).hexdigest()
    return f"search:{digest}"


def web_search_scope_matches(arguments: BaseModel, scope: str) -> bool:
    query = getattr(arguments, "query", None)
    return isinstance(query, str) and scope == web_search_scope(query)


def daily_plan_scope(plan_date: date) -> str:
    return f"life/daily-plans/{plan_date.isoformat()}"


def daily_plan_scope_matches(arguments: BaseModel, scope: str) -> bool:
    plan_date = getattr(arguments, "plan_date", None)
    return isinstance(plan_date, date) and scope == daily_plan_scope(plan_date)


def is_work_handler(handler: str) -> bool:
    return handler in WORK_HANDLERS


def is_work_write_handler(handler: str) -> bool:
    return handler in WORK_WRITE_HANDLERS
