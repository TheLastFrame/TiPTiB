from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict[str, object]:
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


settings = get_settings()

if settings.database_url.startswith("sqlite:///"):
    db_path = settings.database_url.removeprefix("sqlite:///")
    if db_path not in (":memory:", ""):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(settings.database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
