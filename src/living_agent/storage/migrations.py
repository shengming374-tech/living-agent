"""Programmatic Alembic migration entrypoint."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations(database_url: str) -> None:
    with _migration_directory() as migration_root:
        alembic_config = Config()
        alembic_config.set_main_option("script_location", str(migration_root))
        alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(alembic_config, "head")


@contextmanager
def _migration_directory() -> Iterator[Path]:
    project_root = Path(__file__).resolve().parents[3]
    source_migrations = project_root / "migrations"
    if source_migrations.is_dir():
        yield source_migrations
        return

    bundled = resources.files("living_agent").joinpath("_assets", "migrations")
    if not bundled.is_dir():
        raise RuntimeError("packaged Alembic migrations are missing")
    with resources.as_file(bundled) as extracted:
        yield extracted
