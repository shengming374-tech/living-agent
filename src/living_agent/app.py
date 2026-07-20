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
from living_agent.api.persona import router as persona_router
from living_agent.api.plugins import router as plugins_router
from living_agent.api.prompts import router as prompts_router
from living_agent.api.psyche import router as psyche_router
from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.config import Settings, load_settings
from living_agent.evaluation.continuity_critic import ContinuityCritic
from living_agent.evaluation.task_verifier import CalculatorTaskVerifier
from living_agent.execution.broker import CapabilityBroker, CapabilityDefinition
from living_agent.execution.contracts import CALCULATOR_CAPABILITY, CalculatorArguments
from living_agent.execution.executor import CalculatorTaskExecutor
from living_agent.interaction.turn_gate import TurnGate
from living_agent.logging import configure_logging
from living_agent.management.artifacts import ArtifactRepository
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.repository import MemoryRepository
from living_agent.memory.service import MemoryService
from living_agent.persona.manager import PersonaManager
from living_agent.platforms.napcat.adapter import NapCatAdapter
from living_agent.platforms.napcat.api import router as napcat_router
from living_agent.platforms.napcat.models import (
    NAPCAT_REPLY_CAPABILITY,
    NapCatReplyArguments,
    napcat_reply_scope_matches,
)
from living_agent.platforms.openclaw.adapter import OpenClawBridgeAdapter
from living_agent.platforms.openclaw.api import router as openclaw_router
from living_agent.platforms.openclaw.models import (
    OPENCLAW_REPLY_CAPABILITY,
    OpenClawReplyArguments,
    openclaw_reply_scope_matches,
)
from living_agent.plugins.process import PluginProcess
from living_agent.plugins.registry import PluginRegistry
from living_agent.prompts.manager import PromptManager
from living_agent.providers.llm import LLMProvider, MockLLMProvider
from living_agent.psyche.repository import PsycheRepository
from living_agent.psyche.service import PsycheService
from living_agent.runtime.event_bus import EventBus
from living_agent.runtime.runtime import AgentRuntime
from living_agent.storage.database import Database
from living_agent.storage.events import EventRepository
from living_agent.storage.migrations import run_migrations
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.boundary import TrustBoundary


def create_app(
    settings: Settings | None = None,
    *,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings.log_level)
    database = Database(resolved_settings.database_url)
    authority = AuthorityResolver(
        owner_id=resolved_settings.owner_id,
        admin_ids=frozenset(resolved_settings.admin_ids),
    )
    audit = AuditService(database.sessions)
    artifact_repository = ArtifactRepository(database.sessions)
    broker = CapabilityBroker(authority=authority, audit=audit)
    broker.register_capability(
        CapabilityDefinition(
            name=CALCULATOR_CAPABILITY,
            operations=frozenset({"execute"}),
            argument_model=CalculatorArguments,
            sandbox_required=True,
        )
    )
    broker.register_capability(
        CapabilityDefinition(
            name=OPENCLAW_REPLY_CAPABILITY,
            operations=frozenset({"reply"}),
            argument_model=OpenClawReplyArguments,
            scope_validator=openclaw_reply_scope_matches,
        )
    )
    broker.register_capability(
        CapabilityDefinition(
            name=NAPCAT_REPLY_CAPABILITY,
            operations=frozenset({"reply"}),
            argument_model=NapCatReplyArguments,
            scope_validator=napcat_reply_scope_matches,
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
    psyche_service = PsycheService(
        repository=PsycheRepository(database.sessions),
        events=EventRepository(database.sessions),
        audit=audit,
        decay_half_life_hours=resolved_settings.psyche_decay_half_life_hours,
    )
    continuity_critic = ContinuityCritic(
        psyche=psyche_service,
        memories=memory_service,
        audit=audit,
    )
    persona_manager = PersonaManager(
        root=resolved_settings.persona_root,
        repository=artifact_repository,
        audit=audit,
        bootstrap_actor=resolved_settings.owner_id,
    )
    prompt_manager = PromptManager(
        root=resolved_settings.prompt_root,
        repository=artifact_repository,
        audit=audit,
        bootstrap_actor=resolved_settings.owner_id,
    )
    root_policy = (
        f"{prompt_manager.root_policy().strip()}\n\n"
        f"PERSONA IDENTITY:\n{persona_manager.identity_statement()}"
    )
    task_executor = CalculatorTaskExecutor(
        registry=plugin_registry,
        process=PluginProcess(timeout_seconds=resolved_settings.plugin_timeout_seconds),
        broker=broker,
        audit=audit,
        verifier=CalculatorTaskVerifier(),
    )
    trust_boundary = TrustBoundary(authority)
    context_compiler = ContextCompiler()
    runtime = AgentRuntime(
        boundary=trust_boundary,
        events=EventRepository(database.sessions),
        audit=audit,
        event_bus=EventBus(),
        social=SocialCognition(TurnGate()),
        executive=ExecutiveCognition(),
        task_executor=task_executor,
        context_compiler=context_compiler,
        llm=llm_provider or MockLLMProvider(),
        root_policy=root_policy,
        psyche=psyche_service,
        continuity_critic=continuity_critic,
    )
    napcat_adapter = NapCatAdapter(
        enabled=resolved_settings.napcat_enabled,
        access_token=resolved_settings.napcat_access_token,
        runtime=runtime,
        broker=broker,
        audit=audit,
        action_timeout_seconds=resolved_settings.napcat_action_timeout_seconds,
        max_message_chars=resolved_settings.napcat_max_message_chars,
        max_frame_bytes=resolved_settings.napcat_max_frame_bytes,
        max_in_flight_events=resolved_settings.napcat_max_in_flight_events,
    )
    openclaw_bridge_adapter = OpenClawBridgeAdapter(
        enabled=resolved_settings.openclaw_bridge_enabled,
        access_token=resolved_settings.openclaw_bridge_access_token,
        allowed_channels=resolved_settings.openclaw_bridge_allowed_channels,
        allowed_account_ids=resolved_settings.openclaw_bridge_allowed_account_ids,
        max_message_chars=resolved_settings.openclaw_bridge_max_message_chars,
        idempotency_entries=resolved_settings.openclaw_bridge_idempotency_entries,
        runtime=runtime,
        broker=broker,
        audit=audit,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(run_migrations, resolved_settings.database_url)
        await persona_manager.initialize()
        await prompt_manager.initialize()
        await psyche_service.initialize()
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
    app.state.persona_manager = persona_manager
    app.state.prompt_manager = prompt_manager
    app.state.psyche_service = psyche_service
    app.state.napcat_adapter = napcat_adapter
    app.state.openclaw_bridge_adapter = openclaw_bridge_adapter
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(audit_router)
    app.include_router(plugins_router)
    app.include_router(memories_router)
    app.include_router(persona_router)
    app.include_router(prompts_router)
    app.include_router(psyche_router)
    app.include_router(napcat_router)
    app.include_router(openclaw_router)
    return app


app = create_app()
