"""Request-scoped access to host-owned services."""

from fastapi import Request

from living_agent.audit.service import AuditService
from living_agent.config import Settings
from living_agent.execution.broker import CapabilityBroker
from living_agent.execution.service import TaskService
from living_agent.life.self_change import SelfChangeService
from living_agent.life.service import LifeService
from living_agent.memory.service import MemoryService
from living_agent.persona.manager import PersonaManager
from living_agent.plugins.registry import PluginRegistry
from living_agent.prompts.manager import PromptManager
from living_agent.providers.embeddings import EmbeddingService
from living_agent.psyche.service import PsycheService
from living_agent.runtime.runtime import AgentRuntime
from living_agent.trust.authority import AuthorityResolver
from living_agent.users.service import UserService


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime  # type: ignore[no-any-return]


def get_audit(request: Request) -> AuditService:
    return request.app.state.audit  # type: ignore[no-any-return]


def get_authority(request: Request) -> AuthorityResolver:
    return request.app.state.authority  # type: ignore[no-any-return]


def get_plugin_registry(request: Request) -> PluginRegistry:
    return request.app.state.plugin_registry  # type: ignore[no-any-return]


def get_memory_service(request: Request) -> MemoryService:
    return request.app.state.memory_service  # type: ignore[no-any-return]


def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.embedding_service  # type: ignore[no-any-return]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_persona_manager(request: Request) -> PersonaManager:
    return request.app.state.persona_manager  # type: ignore[no-any-return]


def get_prompt_manager(request: Request) -> PromptManager:
    return request.app.state.prompt_manager  # type: ignore[no-any-return]


def get_psyche_service(request: Request) -> PsycheService:
    return request.app.state.psyche_service  # type: ignore[no-any-return]


def get_user_service(request: Request) -> UserService:
    return request.app.state.user_service  # type: ignore[no-any-return]


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service  # type: ignore[no-any-return]


def get_broker(request: Request) -> CapabilityBroker:
    return request.app.state.broker  # type: ignore[no-any-return]


def get_life_service(request: Request) -> LifeService:
    return request.app.state.life_service  # type: ignore[no-any-return]


def get_self_change_service(request: Request) -> SelfChangeService:
    return request.app.state.self_change_service  # type: ignore[no-any-return]
