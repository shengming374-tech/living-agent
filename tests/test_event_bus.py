from living_agent.models.events import IngressEnvelope, SourceType, TrustedEvent
from living_agent.runtime.event_bus import EventBus
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.boundary import TrustBoundary


async def test_event_bus_publishes_typed_event() -> None:
    received: list[str] = []
    bus = EventBus()

    async def handler(event: TrustedEvent) -> None:
        received.append(event.event_id)

    bus.subscribe("message.received", handler)
    event = TrustBoundary(AuthorityResolver(owner_id="owner-1")).normalize(
        IngressEnvelope(
            content="hello",
            source_type=SourceType.DIRECT_MESSAGE,
            source_identity="member-1",
            authenticated=True,
        )
    )
    await bus.publish(event)

    assert received == [event.event_id]
