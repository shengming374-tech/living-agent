import asyncio
from pathlib import Path

import pytest
from sqlalchemy import inspect

from living_agent.storage.database import Database
from living_agent.storage.migrations import run_migrations


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
        "openclaw_ingress_keys",
        "private_projects",
        "daily_plans",
        "life_activity_logs",
        "diary_entries",
        "sleep_cycles",
        "dream_records",
        "self_change_proposals",
    } <= set(table_names)
