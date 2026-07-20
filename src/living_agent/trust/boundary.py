"""Trust-boundary normalization for all ingress."""

from living_agent.models.events import IngressEnvelope, TrustedEvent, TrustLevel
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.taint import classify_taint


class TrustBoundary:
    def __init__(self, authority: AuthorityResolver) -> None:
        self._authority = authority

    def normalize(self, envelope: IngressEnvelope) -> TrustedEvent:
        authority = self._authority.resolve(
            envelope.source_identity,
            authenticated=envelope.authenticated,
        )
        trust_level = TrustLevel.AUTHENTICATED if envelope.authenticated else TrustLevel.UNTRUSTED
        return TrustedEvent(
            event_type=envelope.event_type,
            content=envelope.content,
            source_type=envelope.source_type,
            source_identity=envelope.source_identity,
            conversation_id=envelope.conversation_id,
            trust_level=trust_level,
            authority_level=authority,
            taint_labels=classify_taint(envelope.source_type, envelope.content),
        )
