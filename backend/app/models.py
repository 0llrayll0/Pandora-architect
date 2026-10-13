"""Modelos SQLModel persistidos pelo Pandora Architect.

Uma análise (`AnalysisRun`) forma um snapshot consistente: todos os registros
derivados (`FileMeta`, `Symbol`, `Dependency`, `Metric`) carregam ``run_id`` e
são gravados na mesma transação de run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlmodel import JSON, Column, Field, Index, SQLModel


def utcnow() -> datetime:
    """Timestamp consciente de fuso (UTC)."""
    return datetime.now(UTC)


class RunState(StrEnum):
    """Estado de uma execução de análise."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DependencyClass(StrEnum):
    """Classificação honesta de um import."""

    CONFIRMED = "confirmed"  # resolveu para arquivo dentro do projeto
    EXTERNAL = "external"  # biblioteca externa / stdlib
    UNRESOLVED = "unresolved"  # não foi possível resolver


class Project(SQLModel, table=True):
    """Repositório local registrado pelo usuário."""

    __tablename__ = "projects"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=200)
    path: str = Field(index=True, max_length=1024)  # canônico, absoluto
    description: str = Field(default="", max_length=1000)

    # Exceções configuráveis por projeto (sobrescrevem os padrões)
    extra_excluded_dirs: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    extra_excluded_globs: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    include_hidden: bool = False
    follow_symlinks: bool = False

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        Index("ix_projects_project_id_name", "name"),
        Index("ix_projects_project_id_path", "path"),
    )


class AnalysisRun(SQLModel, table=True):
    """Uma execução de análise (snapshot consistente de um projeto)."""

    __tablename__ = "analysis_runs"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")

    state: str = Field(default=RunState.PENDING.value, index=True)
    progress: float = Field(default=0.0)  # 0..100
    stage: str = Field(default="queued", max_length=64)

    files_total: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0

    symbols_count: int = 0
    dependencies_count: int = 0
    modules_count: int = 0
    errors_count: int = 0

    message: str = Field(default="", max_length=500)
    error: str = Field(default="", max_length=2000)

    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        Index("ix_analysis_runs_run_project", "project_id", "created_at"),
        Index("ix_analysis_runs_run_state", "state"),
    )


class FileMeta(SQLModel, table=True):
    """Metadados de um arquivo descoberto durante a análise."""

    __tablename__ = "file_metas"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    project_id: int = Field(index=True)

    path: str = Field(index=True, max_length=1024)  # relativo à raiz do projeto
    absolute_path: str = Field(max_length=1024, default="")
    language: str = Field(default="unknown", max_length=32)
    module: str = Field(default="", index=True, max_length=512)

    size_bytes: int = 0
    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    sha256: str = Field(default="", max_length=64)

    is_python: bool = False
    parse_ok: bool = True
    parse_error: str = Field(default="", max_length=500)
    is_package: bool = False  # __init__.py

    __table_args__ = (
        Index("ix_file_metas_run_path", "run_id", "path"),
        Index("ix_file_metas_run_module", "run_id", "module"),
    )


class Symbol(SQLModel, table=True):
    """Símbolo extraído (módulo, classe, função ou método)."""

    __tablename__ = "symbols"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    project_id: int = Field(index=True)
    file_id: int | None = Field(default=None, index=True)

    name: str = Field(index=True, max_length=300)
    qualified_name: str = Field(index=True, max_length=600)
    kind: str = Field(default="function", max_length=32)  # module|class|function|method
    module: str = Field(default="", index=True, max_length=512)

    lineno: int = 0
    end_lineno: int = 0
    is_public: bool = True
    is_async: bool = False
    is_test: bool = False

    signature: str = Field(default="", max_length=1000)
    docstring: str = Field(default="", max_length=2000)
    decorators: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    bases: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    calls: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    params_count: int = 0
    complexity: int = 0

    __table_args__ = (
        Index("ix_symbols_run_name", "run_id", "name"),
        Index("ix_symbols_run_kind", "run_id", "kind"),
        Index("ix_symbols_run_qname", "run_id", "qualified_name"),
    )


class Dependency(SQLModel, table=True):
    """Aresta de import entre módulos/arquivos."""

    __tablename__ = "dependencies"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    project_id: int = Field(index=True)

    source_file_id: int | None = Field(default=None, index=True)
    source_path: str = Field(index=True, max_length=1024)
    source_module: str = Field(default="", max_length=512)

    raw: str = Field(default="", max_length=600)  # texto original do import
    module: str = Field(default="", max_length=512)  # módulo referenciado
    level: int = 0  # 0 = absoluto, >0 = relativo
    names: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )

    target_file_id: int | None = Field(default=None, index=True)
    target_path: str = Field(default="", max_length=1024)
    target_module: str = Field(default="", max_length=512)

    classification: str = Field(default=DependencyClass.UNRESOLVED.value, index=True)
    confidence: float = 1.0
    is_star: bool = False

    __table_args__ = (
        Index("ix_dependencies_run_class", "run_id", "classification"),
        Index("ix_dependencies_run_source", "run_id", "source_path"),
    )


class Metric(SQLModel, table=True):
    """Métrica numérica derivada (projeto, módulo ou arquivo)."""

    __tablename__ = "metrics"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    project_id: int = Field(index=True)
    file_id: int | None = Field(default=None, index=True)

    scope: str = Field(default="project", max_length=16)  # project|file|module
    module: str = Field(default="", max_length=512)
    key: str = Field(index=True, max_length=64)
    value: float = 0.0

    __table_args__ = (
        Index("ix_metrics_run_key", "run_id", "key"),
        Index("ix_metrics_run_scope_key", "run_id", "scope", "key"),
    )


class RunMetricSnapshot(SQLModel, table=True):
    """Cache das métricas arquiteturais derivadas do grafo (Fase 2).

    Gravado na mesma transação da run (ou calculado sob demanda e persistido)
    para que ``/metrics`` e ``/hotspots`` não recalculem o grafo a cada chamada.
    """

    __tablename__ = "run_metrics"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True, unique=True)
    project_id: int = Field(index=True)

    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    created_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    """Configuração-chave persistida (overrides operacionais)."""

    __tablename__ = "settings"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, max_length=100, unique=True)
    value: Any = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    updated_at: datetime = Field(default_factory=utcnow)
