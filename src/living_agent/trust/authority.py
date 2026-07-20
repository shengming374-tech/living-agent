"""Identity-backed authority resolution."""

from dataclasses import dataclass

from living_agent.models.events import AuthorityLevel


@dataclass(frozen=True, slots=True)
class AuthorityResolver:
    """Resolve authority only from adapter-authenticated stable identifiers."""

    owner_id: str
    admin_ids: frozenset[str] = frozenset()

    def resolve(self, source_identity: str | None, *, authenticated: bool) -> AuthorityLevel:
        if not authenticated or source_identity is None:
            return AuthorityLevel.ANONYMOUS
        if source_identity == self.owner_id:
            return AuthorityLevel.OWNER
        if source_identity in self.admin_ids:
            return AuthorityLevel.ADMIN
        return AuthorityLevel.MEMBER
