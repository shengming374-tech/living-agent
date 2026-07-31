"""Resolve mutable runtime assets without depending on a source checkout."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from living_agent.config import Settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_ROOT = Path("config")
_DEFAULT_PERSONA_ROOT = Path("personas/default")
_DEFAULT_PROMPT_ROOT = Path("prompts")
_DEFAULT_PLUGIN_ROOT = Path("plugins/examples")

_REQUIRED_PERSONA_FILES = frozenset(
    {
        "boundaries.yaml",
        "growth.yaml",
        "identity.yaml",
        "speech.yaml",
        "traits.yaml",
        "values.yaml",
    }
)
_REQUIRED_PROMPT_FILES = frozenset(
    {
        "evaluation/critic.txt",
        "executive/task.txt",
        "host/root.txt",
        "interaction/turn.txt",
        "memory/candidate.txt",
        "psyche/appraisal.txt",
        "social/reply.txt",
        "speech/render.txt",
    }
)
_REQUIRED_PLUGIN_FILES = frozenset(
    {
        "calculator/manifest.yaml",
        "calculator/plugin/__init__.py",
        "calculator/plugin/main.py",
    }
)


class RuntimeAssetError(RuntimeError):
    """Raised when configured runtime assets cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class RuntimeAssetRoots:
    config: Path
    persona: Path
    prompts: Path
    plugins: Path


def prepare_runtime_assets(settings: Settings) -> RuntimeAssetRoots:
    """Resolve source assets or initialize packaged defaults into the runtime root."""

    runtime_root = settings.runtime_root.expanduser().resolve()
    return RuntimeAssetRoots(
        config=_prepare_root(
            configured=_DEFAULT_CONFIG_ROOT,
            default=_DEFAULT_CONFIG_ROOT,
            runtime_root=runtime_root,
            bundled_path="config",
            required_files=frozenset({"default.yaml"}),
            label="config",
        ),
        persona=_prepare_root(
            configured=settings.persona_root,
            default=_DEFAULT_PERSONA_ROOT,
            runtime_root=runtime_root,
            bundled_path="personas/default",
            required_files=_REQUIRED_PERSONA_FILES,
            label="persona",
        ),
        prompts=_prepare_root(
            configured=settings.prompt_root,
            default=_DEFAULT_PROMPT_ROOT,
            runtime_root=runtime_root,
            bundled_path="prompts",
            required_files=_REQUIRED_PROMPT_FILES,
            label="prompt",
        ),
        plugins=_prepare_root(
            configured=settings.plugin_root,
            default=_DEFAULT_PLUGIN_ROOT,
            runtime_root=runtime_root,
            bundled_path="plugins/examples",
            required_files=_REQUIRED_PLUGIN_FILES,
            label="plugin",
        ),
    )


def _prepare_root(
    *,
    configured: Path,
    default: Path,
    runtime_root: Path,
    bundled_path: str,
    required_files: frozenset[str],
    label: str,
) -> Path:
    expanded = configured.expanduser()
    target = expanded.resolve() if expanded.is_absolute() else (runtime_root / expanded).resolve()
    is_default = configured == default
    if target.exists():
        if not target.is_dir():
            raise RuntimeAssetError(f"{label} root is not a directory: {target}")
        if is_default:
            _require_complete(target, required_files=required_files, label=label)
        return target
    if not is_default:
        raise RuntimeAssetError(f"configured {label} root does not exist: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with _default_asset_directory(bundled_path) as source:
        try:
            shutil.copytree(source, target)
        except FileExistsError as exc:
            raise RuntimeAssetError(
                f"{label} root appeared during initialization: {target}"
            ) from exc
    _require_complete(target, required_files=required_files, label=label)
    return target


def _require_complete(root: Path, *, required_files: frozenset[str], label: str) -> None:
    missing = sorted(path for path in required_files if not (root / path).is_file())
    if missing:
        raise RuntimeAssetError(
            f"default {label} root is incomplete at {root}: missing {', '.join(missing)}"
        )


@contextmanager
def _default_asset_directory(relative_path: str) -> Iterator[Path]:
    source_path = _PROJECT_ROOT / relative_path
    if source_path.is_dir():
        yield source_path
        return

    bundled = resources.files("living_agent").joinpath("_assets", *relative_path.split("/"))
    if not bundled.is_dir():
        raise RuntimeAssetError(f"packaged default asset directory is missing: {relative_path}")
    with resources.as_file(bundled) as extracted:
        yield extracted
