from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

import httpx2
import pytest
from rich.console import Console

from living_agent.cli.psyche import (
    DEFAULT_URL,
    PsycheApiClient,
    PsycheCliError,
    PsycheDashboard,
    PsycheSnapshot,
    _token_for_url,
    build_parser,
)
from living_agent.models.psyche import (
    ActivityRecord,
    ActivityStatus,
    PsycheState,
    ThoughtRecord,
    UnresolvedTopic,
)


def _snapshot() -> PsycheSnapshot:
    now = datetime.now(UTC)
    return PsycheSnapshot(
        state=PsycheState(
            state_id="primary",
            valence=0.65,
            arousal=0.4,
            current_focus="Review the migration plan",
            focus_salience=0.75,
            unresolved_topic_ids=["topic-1"],
            current_activity_id=None,
            last_decay_at=now,
            updated_at=now,
            version=4,
        ),
        thoughts=[
            ThoughtRecord(
                thought_id="thought-1",
                kind="reaction",
                summary="The event warranted a reply.",
                source_event_ids=["event-1"],
                intensity=0.8,
                speakability=0.7,
                created_at=now,
            )
        ],
        topics=[
            UnresolvedTopic(
                topic_id="topic-1",
                summary="Return to the migration review",
                source_event_ids=["event-1"],
                status="open",
                created_at=now,
            )
        ],
        activities=[
            ActivityRecord(
                activity_id="activity-1",
                kind="calculator_task",
                summary="Calculate a verified result",
                source_event_ids=["event-1"],
                status=ActivityStatus.COMPLETED,
                evidence_ids=["evidence-1"],
                started_at=now,
                finished_at=now,
            )
        ],
        fetched_at=now,
    )


def test_dashboard_renders_color_and_all_psyche_sections() -> None:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        width=110,
    )

    console.print(PsycheDashboard(_snapshot(), base_url="http://localhost:8000"))

    rendered = output.getvalue()
    assert "\x1b[" in rendered
    assert "心理状态" in rendered
    assert "近期安全想法" in rendered
    assert "未解决话题" in rendered
    assert "近期活动" in rendered
    assert "Review the migration plan" in rendered


@pytest.mark.asyncio
async def test_api_client_fetches_views_with_owner_authentication() -> None:
    snapshot = _snapshot()
    requested_paths: set[str] = set()

    def handler(request: httpx2.Request) -> httpx2.Response:
        requested_paths.add(request.url.path)
        assert request.headers["X-Actor-ID"] == "owner-1"
        assert request.headers["Authorization"] == "Bearer secret-token"
        payloads = {
            "/v1/psyche/state": snapshot.state.model_dump(mode="json"),
            "/v1/psyche/thoughts": [
                item.model_dump(mode="json") for item in snapshot.thoughts
            ],
            "/v1/psyche/topics": [item.model_dump(mode="json") for item in snapshot.topics],
            "/v1/psyche/activities": [
                item.model_dump(mode="json") for item in snapshot.activities
            ],
        }
        return httpx2.Response(200, json=payloads[request.url.path])

    async with PsycheApiClient(
        base_url="http://testserver",
        actor_id="owner-1",
        token="secret-token",
        timeout_seconds=1,
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = await client.snapshot(limit=12, include_resolved=False)

    assert result.state == snapshot.state
    assert result.thoughts == snapshot.thoughts
    assert requested_paths == {
        "/v1/psyche/state",
        "/v1/psyche/thoughts",
        "/v1/psyche/topics",
        "/v1/psyche/activities",
    }


@pytest.mark.asyncio
async def test_api_client_reports_authentication_failure_without_leaking_token() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(401, json={"detail": "management_token_invalid"})

    async with PsycheApiClient(
        base_url="http://testserver",
        actor_id="owner-1",
        token="do-not-display",
        timeout_seconds=1,
        transport=httpx2.MockTransport(handler),
    ) as client:
        with pytest.raises(PsycheCliError, match="管理令牌缺失或无效") as caught:
            await client.snapshot(limit=12, include_resolved=False)

    assert "do-not-display" not in str(caught.value)


def test_parser_supports_show_watch_and_color_modes() -> None:
    parser = build_parser()

    show = parser.parse_args(["--color", "never", "show", "--limit", "5"])
    watch = parser.parse_args(["watch", "--interval", "0.5", "--include-resolved"])

    assert show.command == "show"
    assert show.color == "never"
    assert show.limit == 5
    assert watch.command == "watch"
    assert watch.interval == 0.5
    assert watch.include_resolved is True


def test_api_client_rejects_remote_plaintext_http() -> None:
    with pytest.raises(PsycheCliError, match="必须使用 HTTPS"):
        PsycheApiClient(
            base_url="http://203.0.113.10:8000",
            actor_id="owner-1",
            token="owner-secret",
            timeout_seconds=1,
        )


def test_default_token_is_not_reused_for_another_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "living_agent.cli.psyche._control_plane_defaults",
        lambda: ("owner-1", "owner-secret"),
    )

    assert _token_for_url(DEFAULT_URL, None) == "owner-secret"
    assert _token_for_url("https://control.example", None) is None
    assert _token_for_url("https://control.example", "explicit-secret") == "explicit-secret"
