from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'living-agent-test.db'}",
        owner_id="owner-1",
        admin_ids=["admin-1"],
        test_disable_delays=True,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
