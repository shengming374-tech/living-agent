from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from living_agent.audit.models import AuditRecordORM
from living_agent.execution.models import TaskReportORM, TaskRunORM
from living_agent.interaction.models import (
    AttentionCueORM,
    ConversationRuntimeStateORM,
    SessionImpressionORM,
    UtteranceSessionORM,
)
from living_agent.life.models import (
    DailyPlanORM,
    DiaryEntryORM,
    DreamRecordORM,
    LifeActivityLogORM,
    PrivateProjectORM,
    SelfChangeProposalORM,
    SleepCycleORM,
)
from living_agent.management.models import ArtifactStageORM, ArtifactVersionORM
from living_agent.memory.models import (
    MemoryCandidateORM,
    MemoryEmbeddingORM,
    MemoryNodeORM,
    MemoryUsageORM,
    MemoryVersionORM,
)
from living_agent.platforms.napcat.storage import NapCatIngressORM
from living_agent.platforms.openclaw.storage import OpenClawIngressORM
from living_agent.psyche.models import (
    ActivityRecordORM,
    PsycheStateORM,
    ThoughtRecordORM,
    UnresolvedTopicORM,
)
from living_agent.storage.database import Base
from living_agent.storage.models import TrustedEventORM
from living_agent.users.models import RegisteredUserORM

_ = (
    AuditRecordORM,
    AttentionCueORM,
    ArtifactStageORM,
    ArtifactVersionORM,
    ActivityRecordORM,
    DailyPlanORM,
    ConversationRuntimeStateORM,
    DiaryEntryORM,
    DreamRecordORM,
    LifeActivityLogORM,
    MemoryCandidateORM,
    MemoryEmbeddingORM,
    MemoryNodeORM,
    MemoryUsageORM,
    MemoryVersionORM,
    NapCatIngressORM,
    OpenClawIngressORM,
    PrivateProjectORM,
    PsycheStateORM,
    ThoughtRecordORM,
    SelfChangeProposalORM,
    SessionImpressionORM,
    SleepCycleORM,
    TaskReportORM,
    TaskRunORM,
    TrustedEventORM,
    UtteranceSessionORM,
    UnresolvedTopicORM,
    RegisteredUserORM,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
