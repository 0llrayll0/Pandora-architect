"""Acesso a dados: SQLModel + SQLite.

Cada análise é gravada em uma transação única (ver ``analysis/pipeline.py``).
O engine é reconfigurável para testes via ``configure_engine()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, create_engine

from .config import Settings, get_settings

_engine: Any = None
_engine_url: str | None = None


def _build_engine(settings: Settings) -> Any:
    """Cria o engine SQLite garantindo o diretório de dados."""
    db_path: Path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def get_engine(settings: Settings | None = None) -> Any:
    """Engine global (lazy) ou o configurado explicitamente nos testes."""
    global _engine, _engine_url
    if _engine is None:
        s = settings or get_settings()
        _engine = _build_engine(s)
        _engine_url = f"sqlite:///{s.db_path}"
    return _engine


def configure_engine(url: str) -> Any:
    """Troca o engine (usado pelos testes com SQLite em arquivo temporário)."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    connect_args: dict[str, Any] = {"check_same_thread": False}
    if url.startswith("sqlite"):
        connect_args["timeout"] = 30
    _engine = create_engine(url, echo=False, connect_args=connect_args)
    _engine_url = url
    return _engine


def reset_engine() -> None:
    """Descarta o engine atual (próxima chamada recria a partir das settings)."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None


# Colunas que podem faltar em bancos criados por versões anteriores.
_LIGHT_MIGRATIONS: dict[str, dict[str, str]] = {
    "projects": {"description": "TEXT NOT NULL DEFAULT ''"},
    "analysis_runs": {"stage": "TEXT NOT NULL DEFAULT 'queued'"},
    "file_metas": {"is_package": "BOOLEAN NOT NULL DEFAULT 0"},
}


def _light_migration(engine: Any) -> None:
    """Migração leve: adiciona colunas ausentes quando o schema evoluir."""
    from sqlalchemy import text

    with engine.connect() as conn:  # type: ignore[attr-defined]
        for table, columns in _LIGHT_MIGRATIONS.items():
            try:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            except Exception:  # pragma: no cover - tabela ainda não existe
                continue
            if not rows:
                continue
            existing = {row[1] for row in rows}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        conn.commit()


def init_db(settings: Settings | None = None) -> None:
    """Importa os modelos, cria as tabelas e aplica a migração leve."""
    from . import models  # noqa: F401  (registro dos modelos)

    engine = get_engine(settings)
    SQLModel.metadata.create_all(engine)
    _light_migration(engine)


def get_session() -> Iterator[Session]:
    """Dependency FastAPI: uma sessão por request."""
    with Session(get_engine()) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sessão transacional para tarefas em background (commit/rollback)."""
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
