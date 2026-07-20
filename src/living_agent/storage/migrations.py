"""Programmatic Alembic migration entrypoint."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations(database_url: str) -> None:
    project_root = Path(__file__).resolve().parents[3]
    alembic_config = Config(project_root / "alembic.ini")
    alembic_config.set_main_option("script_location", str(project_root / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")
