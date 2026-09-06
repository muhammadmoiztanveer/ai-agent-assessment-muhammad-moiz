"""Database engine, session factory, and initialization.

Provides a process-wide SQLAlchemy 2.0 engine and session factory derived from
:class:`app.config.Settings`. The default configuration uses a local SQLite file
(``sqlite:///./data/app.db``), created on demand, so the system persists data with
zero external services. Swapping ``DATABASE_URL`` to Postgres requires no code
changes here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Base

# Populated by init_engine / get_engine.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory for a file-based SQLite database if needed."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    db_path = database_url[len(prefix) :]
    # In-memory SQLite (":memory:") has no filesystem path.
    if not db_path or db_path == ":memory:":
        return
    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def build_engine(settings: Settings) -> Engine:
    """Construct a SQLAlchemy engine for the given settings.

    SQLite needs ``check_same_thread=False`` so a connection can be shared across
    FastAPI's threadpool workers; ``future=True`` selects SQLAlchemy 2.0 semantics.
    """
    connect_args: dict[str, object] = {}
    if settings.is_sqlite:
        _ensure_sqlite_dir(settings.database_url)
        connect_args["check_same_thread"] = False

    return create_engine(
        settings.database_url,
        echo=False,
        future=True,
        connect_args=connect_args,
    )


def init_engine(settings: Settings | None = None, *, create_tables: bool = True) -> Engine:
    """Initialize (or reinitialize) the global engine and session factory.

    Args:
        settings: Optional settings override. Defaults to the cached process settings.
        create_tables: When ``True`` (default), create all tables immediately.

    Returns:
        The configured :class:`sqlalchemy.Engine`.
    """
    global _engine, _session_factory

    settings = settings or get_settings()
    _engine = build_engine(settings)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    if create_tables:
        Base.metadata.create_all(_engine)

    return _engine


def get_engine() -> Engine:
    """Return the global engine, initializing it on first use."""
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the global session factory, initializing the engine on first use."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def init_db(settings: Settings | None = None) -> None:
    """Create all database tables. Safe to call repeatedly (idempotent)."""
    init_engine(settings, create_tables=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope.

    Commits on success, rolls back on any exception, and always closes the session.
    Use for service-layer work outside the FastAPI dependency system.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and guarantees cleanup.

    Note: this does not auto-commit; callers/repositories commit explicitly so
    request handlers stay in control of transaction boundaries.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
