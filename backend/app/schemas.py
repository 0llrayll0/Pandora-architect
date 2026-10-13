"""Schemas de request/response (Pydantic) da API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .models import Project


class ProjectCreate(BaseModel):
    """Payload de criação de projeto (caminho manual)."""

    name: str = Field(default="", max_length=200)
    path: str = Field(min_length=1, max_length=1024)
    description: str = Field(default="", max_length=1000)
    extra_excluded_dirs: list[str] = Field(default_factory=list)
    extra_excluded_globs: list[str] = Field(default_factory=list)
    include_hidden: bool = False

    @field_validator("path")
    @classmethod
    def _strip_path(cls, value: str) -> str:
        return value.strip()


class ProjectUpdate(BaseModel):
    """Atualização parcial de um projeto."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    extra_excluded_dirs: list[str] | None = None
    extra_excluded_globs: list[str] | None = None
    include_hidden: bool | None = None


class RunSummary(BaseModel):
    """Resumo de uma execução de análise."""

    id: int
    project_id: int
    state: str
    progress: float
    stage: str
    files_total: int
    files_processed: int
    files_failed: int
    symbols_count: int
    dependencies_count: int
    modules_count: int
    errors_count: int
    message: str
    error: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class AnalyzeRequest(BaseModel):
    """Payload opcional de disparo de análise."""

    force: bool = False


class ErrorOut(BaseModel):
    """Envelope padrão de erro."""

    detail: str
    code: str


class HealthOut(BaseModel):
    """Resposta do /api/health."""

    status: str
    service: str
    version: str
    database: str
    python: str
    projects: int = 0


class ProjectOut(BaseModel):
    """Projeto com resumo da última análise."""

    id: int
    name: str
    path: str
    description: str
    extra_excluded_dirs: list[str]
    extra_excluded_globs: list[str]
    include_hidden: bool
    created_at: datetime
    updated_at: datetime
    last_run: RunSummary | None = None
    run_count: int = 0

    @classmethod
    def from_model(cls, project: Project, **kwargs: object) -> ProjectOut:
        return cls(
            id=project.id or 0,
            name=project.name,
            path=project.path,
            description=project.description,
            extra_excluded_dirs=list(project.extra_excluded_dirs or []),
            extra_excluded_globs=list(project.extra_excluded_globs or []),
            include_hidden=project.include_hidden,
            created_at=project.created_at,
            updated_at=project.updated_at,
            **kwargs,  # type: ignore[arg-type]
        )
