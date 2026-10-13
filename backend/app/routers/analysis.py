"""Status, progresso (SSE), cancelamento e resultados de uma análise."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, func, select

from ..analysis.metrics import ensure_run_metrics
from ..analysis.pipeline import HUB, is_running
from ..db import get_engine, get_session
from ..errors import conflict
from ..models import AnalysisRun, Dependency, FileMeta, Metric, Project, RunState, Symbol
from ..schemas import RunSummary
from .common import get_run_or_404, run_to_summary

router = APIRouter(prefix="/analysis", tags=["analysis"])

TERMINAL_STATES = {
    RunState.COMPLETED.value,
    RunState.FAILED.value,
    RunState.CANCELLED.value,
}


def _merged_status(session: Session, run: AnalysisRun) -> dict[str, Any]:
    """Status do banco sobrescrito pelo hub em memória (mais fresco)."""
    payload: dict[str, Any] = run_to_summary(run).model_dump()
    live = HUB.snapshot(run.id or 0)
    if live:
        for key in (
            "state",
            "progress",
            "stage",
            "files_total",
            "files_processed",
            "files_skipped",
            "files_failed",
            "symbols_count",
            "dependencies_count",
            "message",
            "error",
        ):
            if live.get(key) not in (None, ""):
                payload[key] = live[key]
    payload["running"] = is_running(run.id or 0)
    return payload


@router.get("/runs/{run_id}")
def run_status(
    run_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Status/progresso de uma análise (percentual, contagens, estado)."""
    run = get_run_or_404(session, run_id)
    return _merged_status(session, run)


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: int,
    after: int = Query(default=-1, description="Última versão recebida pelo cliente"),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Stream SSE de progresso da análise (termina ao concluir/falhar/cancelar)."""
    run = get_run_or_404(session, run_id)

    def _sse(payload: dict[str, Any]) -> str:
        event = payload.get("event", "progress")
        data = json.dumps(payload, ensure_ascii=False, default=str)
        return f"event: {event}\nid: {payload.get('version', 0)}\ndata: {data}\n\n"

    def generator() -> Iterator[str]:
        version = int(after)
        initial = _merged_status(session, run)
        initial["event"] = "progress"
        initial["version"] = version
        yield _sse(initial)

        if run.state in TERMINAL_STATES and not is_running(run.id or 0):
            yield _sse({**initial, "event": "end", "state": run.state})
            return

        while True:
            state = HUB.wait(run.id or 0, version, timeout=15.0)
            if state.get("version", version) <= version:
                # sem mudança: keepalive para o proxy não fechar a conexão
                yield ": keepalive\n\n"
                if not is_running(run.id or 0):
                    # thread terminou sem publicar estado final -> lê o banco
                    with Session(get_engine()) as fresh:
                        row = fresh.get(AnalysisRun, run_id)
                        if row is not None and row.state in TERMINAL_STATES:
                            yield _sse({**_merged_status(fresh, row), "event": "end"})
                            return
                continue
            version = int(state.get("version", version))
            state["event"] = "progress"
            yield _sse(state)
            if state.get("state") in TERMINAL_STATES:
                yield _sse({**state, "event": "end"})
                return

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=RunSummary)
def cancel_run(
    run_id: int, session: Session = Depends(get_session)
) -> RunSummary:
    """Cancela uma análise em execução (rollback do snapshot parcial)."""
    run = get_run_or_404(session, run_id)
    if run.state in TERMINAL_STATES:
        raise conflict(
            f"Análise já finalizada ({run.state}).", code="run_finished"
        )
    HUB.request_cancel(run_id)
    run.state = RunState.CANCELLED.value
    run.stage = "cancelled"
    run.message = "Cancelamento solicitado"
    session.add(run)
    session.commit()
    session.refresh(run)
    return run_to_summary(run)


@router.get("/runs/{run_id}/summary")
def run_summary(
    run_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Pacote compacto para a tela Overview (status + métricas + contagens)."""
    run = get_run_or_404(session, run_id)
    status = _merged_status(session, run)

    metrics_rows = session.exec(
        select(Metric).where(Metric.run_id == run_id, Metric.scope == "project")
    ).all()
    metrics = {row.key: row.value for row in metrics_rows}

    file_count = session.exec(
        select(func.count()).select_from(FileMeta).where(FileMeta.run_id == run_id)
    ).one()
    parse_errors = session.exec(
        select(func.count())
        .select_from(FileMeta)
        .where(FileMeta.run_id == run_id, FileMeta.parse_ok == False)  # noqa: E712
    ).one()

    project = session.get(Project, run.project_id)
    return {
        "run": status,
        "metrics": metrics,
        "files": {"total": file_count, "parse_errors": parse_errors},
        "project": {
            "id": project.id if project else None,
            "name": project.name if project else "",
            "path": project.path if project else "",
        },
    }


def _pagination(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 1000)), max(0, offset)


@router.get("/runs/{run_id}/files")
def list_files(
    run_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    language: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Arquivos do snapshot (paginado)."""
    get_run_or_404(session, run_id)
    limit, offset = _pagination(limit, offset)
    query = select(FileMeta).where(FileMeta.run_id == run_id)
    if language:
        query = query.where(FileMeta.language == language)
    total = session.exec(
        select(func.count()).select_from(query.subquery())
    ).one()
    rows = session.exec(
        query.order_by(FileMeta.path).offset(offset).limit(limit)
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "path": row.path,
                "language": row.language,
                "module": row.module,
                "lines": row.lines,
                "code_lines": row.code_lines,
                "size_bytes": row.size_bytes,
                "parse_ok": row.parse_ok,
                "parse_error": row.parse_error,
                "is_python": row.is_python,
            }
            for row in rows
        ],
    }


@router.get("/runs/{run_id}/symbols")
def list_symbols(
    run_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    kind: str | None = None,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Símbolos extraídos (classes, funções, métodos)."""
    get_run_or_404(session, run_id)
    limit, offset = _pagination(limit, offset)
    query = select(Symbol).where(Symbol.run_id == run_id)
    if kind:
        query = query.where(Symbol.kind == kind)
    if q:
        pattern = f"%{q}%"
        query = query.where(Symbol.name.like(pattern))

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(
        query.order_by(Symbol.complexity.desc(), Symbol.name).offset(offset).limit(limit)
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "qualified_name": row.qualified_name,
                "kind": row.kind,
                "module": row.module,
                "file_id": row.file_id,
                "lineno": row.lineno,
                "complexity": row.complexity,
                "params_count": row.params_count,
                "is_public": row.is_public,
                "is_async": row.is_async,
                "signature": row.signature,
                "docstring": row.docstring,
                "decorators": row.decorators,
                "bases": row.bases,
                "calls": row.calls,
            }
            for row in rows
        ],
    }


@router.get("/runs/{run_id}/dependencies")
def list_dependencies(
    run_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    classification: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Dependências (imports) classificadas como confirmed/external/unresolved."""
    get_run_or_404(session, run_id)
    limit, offset = _pagination(limit, offset)
    query = select(Dependency).where(Dependency.run_id == run_id)
    if classification:
        query = query.where(Dependency.classification == classification)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(query.offset(offset).limit(limit)).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "source_path": row.source_path,
                "source_module": row.source_module,
                "raw": row.raw,
                "module": row.module,
                "level": row.level,
                "names": row.names,
                "target_path": row.target_path,
                "target_module": row.target_module,
                "classification": row.classification,
                "confidence": row.confidence,
            }
            for row in rows
        ],
    }


@router.get("/runs/{run_id}/metrics")
def list_metrics(
    run_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Métricas persistidas (escopo projeto + top por arquivo) + grafo.

    A seção ``graph`` vem do snapshot cacheado por run (``run_metrics``);
    é calculada e persistida sob demanda quando ausente (runs antigas).
    """
    run = get_run_or_404(session, run_id)
    project_rows = session.exec(
        select(Metric).where(Metric.run_id == run_id, Metric.scope == "project")
    ).all()

    file_rows = session.exec(
        select(Metric)
        .where(Metric.run_id == run_id, Metric.scope == "file", Metric.key == "max_complexity")
        .order_by(Metric.value.desc())
        .limit(50)
    ).all()

    package_rows = session.exec(
        select(Metric).where(Metric.run_id == run_id, Metric.scope == "package")
    ).all()
    packages: dict[str, dict[str, float]] = {}
    for row in package_rows:
        packages.setdefault(row.module, {})[row.key] = row.value

    files_by_id = {
        f.id: f.path
        for f in session.exec(select(FileMeta).where(FileMeta.run_id == run_id)).all()
    }
    graph_metrics = ensure_run_metrics(session, run_id, run.project_id)
    return {
        "project": {row.key: row.value for row in project_rows},
        "packages": packages,
        "hotspots": [
            {"path": files_by_id.get(row.file_id or -1, ""), "max_complexity": row.value}
            for row in file_rows
            if row.file_id in files_by_id
        ],
        "graph": {
            "totals": graph_metrics.get("totals", {}),
            "degrees": graph_metrics.get("degrees", {}),
            "betweenness": graph_metrics.get("betweenness", {}),
            "coupling": graph_metrics.get("coupling", []),
            "coupling_summary": graph_metrics.get("coupling_summary", {}),
            "complexity": graph_metrics.get("complexity", {}),
            "cycles": graph_metrics.get("cycles", {}),
            "computed_at": graph_metrics.get("computed_at", ""),
        },
    }


HOTSPOT_NOTE = "indicador para investigação, não defeito comprovado"


@router.get("/runs/{run_id}/hotspots")
def run_hotspots(
    run_id: int,
    limit: int = Query(default=25, ge=1, le=200, description="Máximo de itens"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Hotspots explicáveis por arquivo (score + componentes individuais).

    O score combina complexidade, grau, intermediação e dependências de saída,
    cada componente normalizado em 0-1 com peso explícito. Entre a intermediação
    for estimada (grafo grande), o campo ``estimated`` vem em ``true``.
    """
    run = get_run_or_404(session, run_id)
    payload = ensure_run_metrics(session, run_id, run.project_id)
    hotspots = payload.get("hotspots", [])
    return {
        "run_id": run_id,
        "note": HOTSPOT_NOTE,
        "weights": payload.get("hotspot_weights", {}),
        "betweenness_estimated": payload.get("betweenness", {}).get("estimated", False),
        "total": len(hotspots),
        "limit": limit,
        "items": hotspots[:limit],
    }
