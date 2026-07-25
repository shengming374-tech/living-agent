import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from living_agent.storage.database import Database
from living_agent.storage.migrations import run_migrations


def _alembic_config(database_url: str) -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})")}


@pytest.mark.asyncio
async def test_initial_migration_creates_runtime_tables(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'migrated.db'}"
    await asyncio.to_thread(run_migrations, database_url)
    database = Database(database_url)
    async with database.engine.connect() as connection:
        table_names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    await database.dispose()

    assert {
        "alembic_version",
        "audit_records",
        "trusted_events",
        "memory_candidates",
        "memory_nodes",
        "memory_versions",
        "memory_usages",
        "memory_embeddings",
        "memory_recall_traces",
        "memory_recall_trace_items",
        "artifact_versions",
        "artifact_stages",
        "psyche_states",
        "thought_records",
        "psyche_topics",
        "activity_records",
        "registered_users",
        "task_runs",
        "task_reports",
        "utterance_sessions",
        "conversation_runtime_states",
        "session_impressions",
        "attention_cues",
        "openclaw_ingress_keys",
        "napcat_ingress_keys",
        "private_projects",
        "daily_plans",
        "life_activity_logs",
        "diary_entries",
        "sleep_cycles",
        "dream_records",
        "self_change_proposals",
    } <= set(table_names)


@pytest.mark.asyncio
async def test_dual_layer_memory_migration_preserves_legacy_rows_and_downgrades(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "dual-layer-memory.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    config = _alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "0012_napcat_idempotency")

    now = "2026-07-25 12:00:00"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_candidates (
                candidate_id, proposer_id, memory_type, content, subject,
                source_event_ids, source_trust, factuality, confidence,
                importance, scope, status, decision_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate-legacy",
                "owner",
                "semantic",
                json.dumps("legacy candidate"),
                "legacy candidate",
                json.dumps(["event-legacy"]),
                "authenticated",
                "reported",
                0.8,
                0.7,
                "private:owner",
                "pending",
                None,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_nodes (
                id, memory_type, content, searchable_text, subject,
                source_event_ids, source_trust, factuality, confidence,
                importance, scope, created_at, updated_at, status, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "memory-legacy",
                "semantic",
                json.dumps("legacy memory"),
                "legacy memory",
                "legacy memory",
                json.dumps(["event-legacy"]),
                "authenticated",
                "reported",
                0.8,
                0.7,
                "private:owner",
                now,
                now,
                "active",
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO utterance_sessions (
                session_id, platform, conversation_id, source_event_id, intention,
                units, recalled_memory_ids, attention_cue_id, sent_count,
                started_count, interruption_policy, state, generation,
                replaced_session_id, interruption_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-legacy",
                "napcat",
                "conversation-legacy",
                "event-legacy",
                "reply",
                json.dumps([{"text": "hello"}]),
                json.dumps([]),
                None,
                0,
                0,
                "interruptible",
                "planned",
                1,
                None,
                None,
                now,
                now,
            ),
        )

    await asyncio.to_thread(command.upgrade, config, "head")

    added_memory_columns = {
        "memory_layer",
        "entity_id",
        "memory_key",
        "valid_until",
        "superseded_by_id",
    }
    with sqlite3.connect(database_path) as connection:
        assert added_memory_columns <= _columns(connection, "memory_candidates")
        assert added_memory_columns <= _columns(connection, "memory_nodes")
        assert "memory_trace_id" in _columns(connection, "utterance_sessions")
        assert {
            "memory_recall_traces",
            "memory_recall_trace_items",
        } <= {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert connection.execute(
            """
            SELECT memory_layer, entity_id, memory_key, valid_until, superseded_by_id
            FROM memory_nodes WHERE id = 'memory-legacy'
            """
        ).fetchone() == (None, None, None, None, None)
        assert connection.execute(
            """
            SELECT memory_trace_id
            FROM utterance_sessions WHERE session_id = 'session-legacy'
            """
        ).fetchone() == (None,)

        connection.execute(
            """
            INSERT INTO memory_recall_traces (
                trace_id, event_id, response_id, conversation_id, actor_id,
                route, query_hash, context_fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trace-1",
                "event-legacy",
                None,
                "conversation-legacy",
                "owner",
                "lexical",
                "a" * 64,
                None,
                now,
                now,
            ),
        )
        assert connection.execute(
            "SELECT support_mode FROM memory_recall_traces WHERE trace_id = 'trace-1'"
        ).fetchone() == ("pending",)
        item_values = (
            "row-1",
            "trace-1",
            "memory-legacy",
            "legacy",
            "eligible",
            None,
            None,
            0.7,
            True,
            True,
            None,
            False,
            now,
            now,
        )
        connection.execute(
            """
            INSERT INTO memory_recall_trace_items (
                row_id, trace_id, memory_id, memory_layer, selection_reason,
                lexical_score, semantic_score, final_score, selected, injected,
                response_match, source_overlap, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            item_values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_recall_trace_items (
                    row_id, trace_id, memory_id, memory_layer, selection_reason,
                    lexical_score, semantic_score, final_score, selected, injected,
                    response_match, source_overlap, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("row-2", *item_values[1:]),
            )

    await asyncio.to_thread(command.downgrade, config, "0012_napcat_idempotency")

    with sqlite3.connect(database_path) as connection:
        assert not (added_memory_columns & _columns(connection, "memory_candidates"))
        assert not (added_memory_columns & _columns(connection, "memory_nodes"))
        assert "memory_trace_id" not in _columns(connection, "utterance_sessions")
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_candidates WHERE candidate_id = 'candidate-legacy'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE id = 'memory-legacy'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM utterance_sessions WHERE session_id = 'session-legacy'"
        ).fetchone() == (1,)
        remaining_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "memory_recall_traces" not in remaining_tables
        assert "memory_recall_trace_items" not in remaining_tables
