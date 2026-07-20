from fastapi.testclient import TestClient

from living_agent.audit.service import AuditService


async def test_audit_log_redacts_secret_values(client: TestClient) -> None:
    audit: AuditService = client.app.state.audit
    await audit.append(
        action="tool.called",
        actor_id="member-1",
        outcome="denied",
        details={"api_key": "top-secret", "nested": {"password": "hidden"}},
    )

    entries = await audit.list_entries(limit=10)
    entry = next(item for item in entries if item.action == "tool.called")
    assert entry.details["api_key"] == "[REDACTED]"
    assert entry.details["nested"]["password"] == "[REDACTED]"
    assert "top-secret" not in repr(entry.details)
