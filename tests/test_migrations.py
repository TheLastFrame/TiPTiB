from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_can_upgrade_fresh_sqlite_database(tmp_path: Path):
    db_path = tmp_path / "migration.db"
    db_path.unlink(missing_ok=True)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert {"currency", "timezone"}.issubset(user_columns)
