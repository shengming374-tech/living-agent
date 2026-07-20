import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).parent.parent
    persona_root = tmp_path / "personas" / "default"
    prompt_root = tmp_path / "prompts"
    shutil.copytree(project_root / "personas" / "default", persona_root)
    shutil.copytree(project_root / "prompts", prompt_root)
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'living-agent-test.db'}",
        owner_id="owner-1",
        admin_ids=["admin-1"],
        test_disable_delays=True,
        persona_root=persona_root,
        prompt_root=prompt_root,
        root_prompt_second_factor_sha256=hashlib.sha256(b"test-second-factor").hexdigest(),
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
