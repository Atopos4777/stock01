"""数据库会话与初始化。SQLite 免安装；换 PostgreSQL 只需改 URL。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{settings.db_path}"
        _engine = create_engine(
            url, connect_args={"check_same_thread": False}, pool_pre_ping=True, future=True
        )

        @event.listens_for(_engine, "connect")
        def _set_pragma(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def init_db(reset: bool = False) -> None:
    engine = get_engine()
    if reset and settings.db_path.exists():
        engine.dispose()
        settings.db_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
        # 重建引擎
        global _engine, _SessionLocal
        _engine = None
        _SessionLocal = None
        engine = get_engine()
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Session:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Session:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
