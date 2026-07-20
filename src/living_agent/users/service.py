"""Auto-register authenticated social identities without changing authority."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.models.events import IngressEnvelope, SourceType, TrustedEvent, TrustLevel
from living_agent.models.users import UserProfile
from living_agent.users.repository import UserRepository


class UserService:
    def __init__(self, *, repository: UserRepository, audit: AuditService) -> None:
        self._repository = repository
        self._audit = audit

    async def observe(
        self,
        envelope: IngressEnvelope,
        event: TrustedEvent,
    ) -> UserProfile | None:
        if (
            event.trust_level is not TrustLevel.AUTHENTICATED
            or event.source_identity is None
            or event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}
        ):
            return None
        display_name = self._display_name(envelope.display_name)
        profile, created, name_changed = await self._repository.observe(
            event,
            display_name=display_name,
        )
        if created or name_changed:
            await self._audit.append(
                action="user.registered" if created else "user.profile_updated",
                actor_id=event.source_identity,
                conversation_id=event.conversation_id,
                outcome="success",
                details={
                    "user_id": event.source_identity,
                    "source_type": event.source_type.value,
                    "display_name_changed": name_changed,
                },
            )
        return profile

    async def list(self, *, query: str, limit: int) -> list[UserProfile]:
        return await self._repository.list(query=query, limit=limit)

    async def get(self, user_id: str) -> UserProfile:
        return await self._repository.get(user_id)

    @staticmethod
    def _display_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = "".join(character for character in value if character.isprintable()).strip()
        return normalized[:200] or None
