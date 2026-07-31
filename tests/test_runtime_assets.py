from __future__ import annotations

from pathlib import Path

import pytest

from living_agent.config import Settings
from living_agent.runtime_assets import RuntimeAssetError, prepare_runtime_assets


def runtime_settings(settings: Settings, runtime_root: Path) -> Settings:
    return settings.model_copy(
        update={
            "runtime_root": runtime_root,
            "persona_root": Path("personas/default"),
            "prompt_root": Path("prompts"),
            "plugin_root": Path("plugins/examples"),
        },
        deep=True,
    )


def test_default_runtime_assets_are_initialized_without_overwriting(
    settings: Settings,
    tmp_path: Path,
) -> None:
    configured = runtime_settings(settings, tmp_path / "runtime")

    roots = prepare_runtime_assets(configured)
    identity = roots.persona / "identity.yaml"
    identity.write_text("custom: preserved\n", encoding="utf-8")

    prepared_again = prepare_runtime_assets(configured)

    assert roots.config == tmp_path / "runtime/config"
    assert (roots.config / "default.yaml").is_file()
    assert (roots.prompts / "host/root.txt").is_file()
    assert (roots.plugins / "calculator/manifest.yaml").is_file()
    assert prepared_again.persona == roots.persona
    assert identity.read_text(encoding="utf-8") == "custom: preserved\n"


def test_partial_default_runtime_directory_fails_explicitly(
    settings: Settings,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    persona_root = runtime_root / "personas/default"
    persona_root.mkdir(parents=True)
    (persona_root / "identity.yaml").write_text("identity: partial\n", encoding="utf-8")

    with pytest.raises(RuntimeAssetError, match="default persona root is incomplete"):
        prepare_runtime_assets(runtime_settings(settings, runtime_root))


def test_missing_custom_runtime_directory_is_not_auto_initialized(
    settings: Settings,
    tmp_path: Path,
) -> None:
    configured = runtime_settings(settings, tmp_path / "runtime").model_copy(
        update={"persona_root": Path("custom/persona")}
    )

    with pytest.raises(RuntimeAssetError, match="configured persona root does not exist"):
        prepare_runtime_assets(configured)


def test_explicit_missing_configuration_file_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv("LIVING_AGENT_CONFIG", str(missing))

    with pytest.raises(FileNotFoundError, match="configured settings file does not exist"):
        Settings()
