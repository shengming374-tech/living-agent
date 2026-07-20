"""LivingAgent FastAPI application factory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from living_agent.api.audit import router as audit_router
from living_agent.api.chat import router as chat_router
from living_agent.api.embeddings import router as embeddings_router
from living_agent.api.health import router as health_router
from living_agent.api.memories import router as memories_router
from living_agent.api.persona import router as persona_router
from living_agent.api.plugins import router as plugins_router
from living_agent.api.prompts import router as prompts_router
from living_agent.api.psyche import router as psyche_router
from living_agent.api.tasks import router as tasks_router
from living_agent.api.users import router as users_router
from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.config import Settings, load_settings
from living_agent.evaluation.continuity_critic import ContinuityCritic
from living_agent.evaluation.task_verifier import CalculatorTaskVerifier, TaskPlanVerifier
from living_agent.execution.broker import CapabilityBroker, CapabilityDefinition
from living_agent.execution.contracts import CALCULATOR_CAPABILITY, CalculatorArguments
from living_agent.execution.executor import CalculatorTaskExecutor
from living_agent.execution.kernel import TaskKernel
from living_agent.execution.report import TaskReportExecutor
from living_agent.execution.report_contracts import (
    TASK_REPORT_CAPABILITY,
    TaskReportArguments,
    task_report_scope_matches,
)
from living_agent.execution.repository import TaskRepository
from living_agent.execution.service import TaskService
from living_agent.interaction.turn_gate import TurnGate
from living_agent.logging import configure_logging
from living_agent.management.artifacts import ArtifactRepository
from living_agent.memory.firewall import MemoryFirewall
from living_agent.memory.recall import MemoryRecallService
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
from living_agent.providers.embeddings import (
    EMBEDDING_CAPABILITY,
    EmbeddingCapabilityArguments,
    EmbeddingProvider,
    EmbeddingService,
    MockEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from living_agent.providers.llm import (
    ClosableLLMProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAICompatibleLLMProvider,
)
from living_agent.psyche.repository import PsycheRepository
from living_agent.psyche.service import PsycheService
from living_agent.runtime.event_bus import EventBus
from living_agent.runtime.runtime import AgentRuntime
from living_agent.storage.database import Database
from living_agent.storage.events import EventRepository
from living_agent.storage.migrations import run_migrations
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.boundary import TrustBoundary
from living_agent.users.repository import UserRepository
from living_agent.users.service import UserService


def create_app(
    settings: Settings | None = None,
    *,
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings.log_level)
    database = Database(resolved_settings.database_url)
    authority = AuthorityResolver(
        owner_id=resolved_settings.owner_id,
        admin_ids=frozenset(resolved_settings.admin_ids),
    )
    audit = AuditService(database.sessions)
    user_service = UserService(
        repository=UserRepository(database.sessions),
        audit=audit,
    )
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
            name=TASK_REPORT_CAPABILITY,
            operations=frozenset({"write"}),
            argument_model=TaskReportArguments,
            scope_validator=task_report_scope_matches,
        )
    )
    broker.register_capability(
        CapabilityDefinition(
            name=EMBEDDING_CAPABILITY,
            operations=frozenset({"send"}),
            argument_model=EmbeddingCapabilityArguments,
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
    if embedding_provider is not None:
        resolved_embedding_provider = embedding_provider
    elif resolved_settings.embedding_provider == "mock":
        resolved_embedding_provider = MockEmbeddingProvider(
            model=resolved_settings.embedding_model,
            dimensions=resolved_settings.embedding_dimensions or 32,
        )
    else:
        base_url = resolved_settings.embedding_api_base_url
        if base_url is None:
            raise ValueError("embedding API base URL is not configured")
        resolved_embedding_provider = OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            api_key=resolved_settings.embedding_api_key,
            model=resolved_settings.embedding_model,
            dimensions=resolved_settings.embedding_dimensions,
            timeout_seconds=resolved_settings.embedding_timeout_seconds,
            max_response_bytes=resolved_settings.embedding_max_response_bytes,
        )
    embedding_service = EmbeddingService(
        provider=resolved_embedding_provider,
        broker=broker,
        audit=audit,
        max_batch_size=resolved_settings.embedding_max_batch_size,
        max_input_chars=resolved_settings.embedding_max_input_chars,
        max_total_chars=resolved_settings.embedding_max_total_chars,
    )
    memory_service = MemoryService(
        repository=MemoryRepository(database.sessions),
        events=EventRepository(database.sessions),
        firewall=MemoryFirewall(),
        recall=MemoryRecallService(),
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
    persona_profile = persona_manager.public_profile()
    persona_context = json.dumps(
        persona_profile.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )
    social_policy = prompt_manager.social_reply_policy(
        persona_name=persona_profile.identity.name,
    )
    root_policy = (
        f"{prompt_manager.root_policy().strip()}\n\n"
        "<TRUSTED_PERSONA_PROFILE>\n"
        f"{persona_context}\n"
        "</TRUSTED_PERSONA_PROFILE>\n\n"
        "<SOCIAL_RESPONSE_POLICY>\n"
        f"{social_policy}\n"
        "</SOCIAL_RESPONSE_POLICY>"
    )
    if llm_provider is not None:
        resolved_llm_provider = llm_provider
    elif resolved_settings.model_provider == "mock":
        resolved_llm_provider = MockLLMProvider(model=resolved_settings.model_name)
    else:
        model_base_url = resolved_settings.model_api_base_url
        if model_base_url is None:
            raise ValueError("model API base URL is not configured")
        resolved_llm_provider = OpenAICompatibleLLMProvider(
            base_url=model_base_url,
            api_key=resolved_settings.model_api_key,
            model=resolved_settings.model_name,
            timeout_seconds=resolved_settings.model_timeout_seconds,
            max_output_tokens=resolved_settings.model_max_output_tokens,
            temperature=resolved_settings.model_temperature,
            max_context_chars=resolved_settings.model_max_context_chars,
            max_response_bytes=resolved_settings.model_max_response_bytes,
        )
    calculator_executor = CalculatorTaskExecutor(
        registry=plugin_registry,
        process=PluginProcess(timeout_seconds=resolved_settings.plugin_timeout_seconds),
        broker=broker,
        audit=audit,
        verifier=CalculatorTaskVerifier(),
    )
    task_repository = TaskRepository(database.sessions)
    task_kernel = TaskKernel(
        repository=task_repository,
        calculator=calculator_executor,
        reports=TaskReportExecutor(
            broker=broker,
            repository=task_repository,
            audit=audit,
        ),
        verifier=TaskPlanVerifier(),
        audit=audit,
    )
    task_service = TaskService(
        kernel=task_kernel,
        repository=task_repository,
        psyche=psyche_service,
        authority=authority,
        audit=audit,
    )
    trust_boundary = TrustBoundary(authority)
    context_compiler = ContextCompiler()
    runtime = AgentRuntime(
        boundary=trust_boundary,
        events=EventRepository(database.sessions),
        audit=audit,
        event_bus=EventBus(),
        social=SocialCognition(
            TurnGate(
                engage_units_min=resolved_settings.social_engage_units_min,
                engage_units_max=resolved_settings.social_engage_units_max,
                group_auto_participation=resolved_settings.social_group_auto_participation,
                group_min_user_turns=resolved_settings.social_group_min_user_turns,
                group_cooldown_seconds=resolved_settings.social_group_cooldown_seconds,
            )
        ),
        executive=ExecutiveCognition(),
        tasks=task_service,
        context_compiler=context_compiler,
        llm=resolved_llm_provider,
        root_policy=root_policy,
        psyche=psyche_service,
        continuity_critic=continuity_critic,
        memories=memory_service,
        users=user_service,
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
        del application
        try:
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
            await task_service.initialize()
            yield
        finally:
            try:
                if isinstance(resolved_llm_provider, ClosableLLMProvider):
                    await resolved_llm_provider.close()
            finally:
                try:
                    await embedding_service.close()
                finally:
                    await database.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.authority = authority
    app.state.audit = audit
    app.state.runtime = runtime
    app.state.llm_provider = resolved_llm_provider
    app.state.broker = broker
    app.state.plugin_registry = plugin_registry
    app.state.memory_service = memory_service
    app.state.embedding_service = embedding_service
    app.state.persona_manager = persona_manager
    app.state.prompt_manager = prompt_manager
    app.state.psyche_service = psyche_service
    app.state.user_service = user_service
    app.state.task_repository = task_repository
    app.state.task_kernel = task_kernel
    app.state.task_service = task_service
    app.state.napcat_adapter = napcat_adapter
    app.state.openclaw_bridge_adapter = openclaw_bridge_adapter
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(embeddings_router)
    app.include_router(audit_router)
    app.include_router(plugins_router)
    app.include_router(memories_router)
    app.include_router(persona_router)
    app.include_router(prompts_router)
    app.include_router(psyche_router)
    app.include_router(tasks_router)
    app.include_router(users_router)
    app.include_router(napcat_router)
    app.include_router(openclaw_router)
    return app


app = create_app()
