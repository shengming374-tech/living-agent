"""LivingAgent FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from living_agent.api.audit import router as audit_router
from living_agent.api.chat import router as chat_router
from living_agent.api.health import router as health_router
from living_agent.api.memories import router as memories_router
from living_agent.api.plugins import router as plugins_router
from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.config import Settings, load_settings
from living_agent.evaluation.task_verifier import CalculatorTaskVerifier
from living_agent.execution.broker import CapabilityBroker, CapabilityDefinition
from living_agent.execution.contracts import CALCULATOR_CAPABILITY, CalculatorArguments
from living_agent.execution.executor import CalculatorTaskExecutor
from living_agent.interaction.turn_gate import TurnGate
from living_agent.logging import configure_logging
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.repository import MemoryRepository
from living_agent.memory.service import MemoryService
from living_agent.plugins.process import PluginProcess
from living_agent.plugins.registry import PluginRegistry
from living_agent.providers.llm import MockLLMProvider
from living_agent.runtime.event_bus import EventBus
from living_agent.runtime.runtime import AgentRuntime
from living_agent.storage.database import Database
from living_agent.storage.events import EventRepository
from living_agent.storage.migrations import run_migrations
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.boundary import TrustBoundary


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings.log_level)
    database = Database(resolved_settings.database_url)
    authority = AuthorityResolver(
        owner_id=resolved_settings.owner_id,
        admin_ids=frozenset(resolved_settings.admin_ids),
    )
    audit = AuditService(database.sessions)
    broker = CapabilityBroker(authority=authority, audit=audit)
    broker.register_capability(
        CapabilityDefinition(
            name=CALCULATOR_CAPABILITY,
            operations=frozenset({"execute"}),
            argument_model=CalculatorArguments,
            sandbox_required=True,
        )
    )
    plugin_registry = PluginRegistry(resolved_settings.plugin_root)
    plugin_registry.discover()
    memory_service = MemoryService(
        repository=MemoryRepository(database.sessions),
        events=EventRepository(database.sessions),
        firewall=MemoryFirewall(),
        audit=audit,
    )
    task_executor = CalculatorTaskExecutor(
        registry=plugin_registry,
        process=PluginProcess(timeout_seconds=resolved_settings.plugin_timeout_seconds),
        broker=broker,
        audit=audit,
        verifier=CalculatorTaskVerifier(),
    )
    runtime = AgentRuntime(
        boundary=TrustBoundary(authority),
        events=EventRepository(database.sessions),
        audit=audit,
        event_bus=EventBus(),
        social=SocialCognition(TurnGate()),
        executive=ExecutiveCognition(),
        task_executor=task_executor,
        context_compiler=ContextCompiler(),
        llm=MockLLMProvider(),
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(run_migrations, resolved_settings.database_url)
        await audit.append(
            action="runtime.started",
            actor_id="living-agent",
            outcome="success",
            details={"environment": resolved_settings.environment},
        )
        for plugin_id in resolved_settings.enabled_plugins:
            await plugin_registry.enable(
                plugin_id, actor_id=resolved_settings.owner_id, audit=audit
            )
        yield
        await database.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.authority = authority
    app.state.audit = audit
    app.state.runtime = runtime
    app.state.broker = broker
    app.state.plugin_registry = plugin_registry
    app.state.memory_service = memory_service
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(audit_router)
    app.include_router(plugins_router)
    app.include_router(memories_router)
    return app


app = create_app()
