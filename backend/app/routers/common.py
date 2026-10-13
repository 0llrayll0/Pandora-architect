"""Helpers compartilhados entre os routers."""

from __future__ import annotations

from sqlmodel import Session, select

from ..errors import not_found
from ..models import AnalysisRun, Project
from ..schemas import RunSummary

RUN_STATE_ACTIVE = {"pending", "running"}


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise not_found(f"Projeto {project_id} não encontrado", code="project_not_found")
    return project


def get_run_or_404(session: Session, run_id: int) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise not_found(f"Análise {run_id} não encontrada", code="run_not_found")
    return run


def run_to_summary(run: AnalysisRun) -> RunSummary:
    return RunSummary(
        id=run.id or 0,
        project_id=run.project_id,
        state=run.state,
        progress=run.progress,
        stage=run.stage,
        files_total=run.files_total,
        files_processed=run.files_processed,
        files_failed=run.files_failed,
        symbols_count=run.symbols_count,
        dependencies_count=run.dependencies_count,
        modules_count=run.modules_count,
        errors_count=run.errors_count,
        message=run.message,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def latest_run(session: Session, project_id: int) -> AnalysisRun | None:
    """Run mais recente do projeto."""
    rows = session.exec(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.id.desc())
    ).all()
    return rows[0] if rows else None


def active_run(session: Session, project_id: int) -> AnalysisRun | None:
    """Run pendente/em execução (se houver)."""
    rows = session.exec(
        select(AnalysisRun)
        .where(
            AnalysisRun.project_id == project_id,
            AnalysisRun.state.in_(tuple(RUN_STATE_ACTIVE)),
        )
        .order_by(AnalysisRun.id.desc())
    ).all()
    return rows[0] if rows else None
