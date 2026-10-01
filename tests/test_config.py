from pathlib import Path

import pytest

from living_agent.config import Settings


def test_config_and_dotenv_decode_utf8_on_non_utf8_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    import io

    config = tmp_path / "config.yaml"
    dotenv = tmp_path / ".env"
    config.write_text("owner_id: 配置主人\n", encoding="utf-8")
    dotenv.write_text("LIVING_AGENT_APP_NAME=生活伴侣\n", encoding="utf-8")
    monkeypatch.setenv("LIVING_AGENT_CONFIG", str(config))
    monkeypatch.delenv("LIVING_AGENT_APP_NAME", raising=False)
    original = io.open

    def non_utf8_open(file, *args, **kwargs):
        if not isinstance(file, int) and Path(file) in {config, dotenv}:
            kwargs["encoding"] = kwargs.get("encoding") or "cp1252"
        return original(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", non_utf8_open)
    monkeypatch.setattr(builtins, "open", non_utf8_open)
    settings = Settings(_env_file=dotenv)
    assert settings.owner_id == "配置主人"
    assert settings.app_name == "生活伴侣"
