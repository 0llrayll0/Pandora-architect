"""CRUD de projetos + disparo de análise."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, delete, select

from ..analysis.metrics import ensure_run_metrics
from ..analysis.pipeline import HUB, is_running, start_run
from ..db import get_session
from ..errors import conflict, not_found
from ..models import (
    AnalysisRun,
    Dependency,
    FileMeta,
    Metric,
    Project,
    RunMetricSnapshot,
    RunState,
    Symbol,
)
from ..schemas import AnalyzeRequest, ProjectCreate, ProjectOut, ProjectUpdate, RunSummary
from ..security import canonicalize
from .common import active_run, get_project_or_404, latest_run, run_to_summary

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_out(session: Session, project: Project) -> ProjectOut:
    runs = session.exec(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == (project.id or 0))
        .order_by(AnalysisRun.id.desc())
    ).all()
    summary = run_to_summary(runs[0]) if runs else None
    return ProjectOut.from_model(project, last_run=summary, run_count=len(runs))


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectOut]:
    """Lista todos os projetos cadastrados (mais recente primeiro)."""
    projects = session.exec(select(Project).order_by(Project.id.desc())).all()
    return [_project_out(session, p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate, session: Session = Depends(get_session)
) -> ProjectOut:
    """Registra um projeto a partir de um caminho manual.

    O caminho é canonicalizado e precisa existir, ser diretório e estar sob
    um diretório autorizado (caso contrário → 403).
    """
    path = canonicalize(payload.path, must_exist=True, must_be_dir=True)

    existing = session.exec(select(Project).where(Project.path == str(path))).first()
    if existing is not None:
        raise conflict(
            f"Projeto já cadastrado para {path}", code="project_exists"
        )

    name = payload.name.strip() or path.name or str(path)
    project = Project(
        name=name,
        path=str(path),
        description=payload.description,
        extra_excluded_dirs=payload.extra_excluded_dirs,
        extra_excluded_globs=payload.extra_excluded_globs,
        include_hidden=payload.include_hidden,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return _project_out(session, project)


@router.get("/{project_id}", response_model=ProjectOut)
def read_project(
    project_id: int, session: Session = Depends(get_session)
) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    return _project_out(session, project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
) -> ProjectOut:
    project = get_project_or_404(session, project_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(project, key, value)
    project.updated_at = datetime.now(UTC)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _project_out(session, project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int, session: Session = Depends(get_session)
) -> Response:
    """Remove o projeto do Pandora (NÃO apaga nenhum arquivo em disco)."""
    project = get_project_or_404(session, project_id)

    running = active_run(session, project_id)
    if running is not None and is_running(running.id or 0):
        raise conflict(
            "Há uma análise em execução; cancele antes de remover o projeto.",
            code="analysis_running",
        )

    run_ids = [
        r.id
        for r in session.exec(
            select(AnalysisRun).where(AnalysisRun.project_id == project_id)
        ).all()
        if r.id is not None
    ]
    if run_ids:
        for model in (Dependency, Metric, Symbol, FileMeta, RunMetricSnapshot):
            session.execute(delete(model).where(model.run_id.in_(run_ids)))
        session.execute(delete(AnalysisRun).where(AnalysisRun.id.in_(run_ids)))
    session.delete(project)
    session.commit()
    return Response(status_code=204)


@router.get("/{project_id}/runs", response_model=list[RunSummary])
def list_runs(
    project_id: int, session: Session = Depends(get_session)
) -> list[RunSummary]:
    """Histórico de análises do projeto."""
    get_project_or_404(session, project_id)
    runs = session.exec(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.id.desc())
    ).all()
    return [run_to_summary(r) for r in runs]


@router.get("/{project_id}/analyses")
def list_analyses(
    project_id: int, session: Session = Depends(get_session)
) -> dict:
    """Histórico de análises com contagens + resumo das métricas do grafo.

    Runs antigas sem snapshot de métricas vêm com ``graph: null`` (nada é
    inventado); o snapshot é preenchido quando a run é analisada ou quando
    ``/metrics``/``/hotspots`` é consultado.
    """
    get_project_or_404(session, project_id)
    runs = session.exec(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.id.desc())
    ).all()

    items: list[dict] = []
    for run in runs:
        entry = run_to_summary(run).model_dump()
        snapshot = session.exec(
            select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == (run.id or 0))
        ).first()
        if snapshot is not None and snapshot.payload:
            payload = snapshot.payload
            totals = payload.get("totals", {})
            cycles = payload.get("cycles", {})
            summary = payload.get("coupling_summary", {})
            hotspots = payload.get("hotspots") or []
            entry["graph"] = {
                "nodes": totals.get("nodes", 0),
                "edges": totals.get("edges", 0),
                "weak_components": totals.get("weak_components", 0),
                "strong_components": totals.get("strong_components", 0),
                "cycles": cycles.get("count", 0),
                "avg_instability": summary.get("avg_instability", 0.0),
                "top_hotspot": hotspots[0] if hotspots else None,
            }
        else:
            entry["graph"] = None
        items.append(entry)
    return {"total": len(items), "items": items}


def _run_snapshot(
    session: Session, run: AnalysisRun
) -> dict:
    """Snapshot de métricas da run (calcula e persiste sob demanda)."""
    return ensure_run_metrics(session, run.id or 0, run.project_id)


def _diff_metrics(base: dict, target: dict) -> dict:
    """Variação das métricas totais — só o que existir nos dois snapshots."""
    def pick(payload: dict) -> dict:
        totals = payload.get("totals", {})
        cycles = payload.get("cycles", {})
        summary = payload.get("coupling_summary", {})
        return {
            "nodes": totals.get("nodes"),
            "edges": totals.get("edges"),
            "weak_components": totals.get("weak_components"),
            "strong_components": totals.get("strong_components"),
            "cycles": cycles.get("count"),
            "avg_instability": summary.get("avg_instability"),
        }

    base_values, target_values = pick(base), pick(target)
    diff: dict[str, dict] = {}
    for key in base_values:
        b, t = base_values[key], target_values[key]
        if b is None or t is None:
            continue  # tolerante a estruturas diferentes
        diff[key] = {"base": b, "target": t, "delta": round(t - b, 4)}
    return diff


def _cycle_signature(cycle: list[str]) -> tuple[str, ...]:
    if not cycle:
        return ()
    pivot = cycle.index(min(cycle))
    return tuple([*cycle[pivot:], *cycle[:pivot]])


@router.get("/{project_id}/compare")
def compare_runs(
    project_id: int,
    base: int = Query(..., description="run_id de origem"),
    target: int = Query(..., description="run_id de destino"),
    session: Session = Depends(get_session),
) -> dict:
    """Diff entre duas análises do mesmo projeto.

    Compara arquivos (hash), símbolos, dependências (pares src→dst), métricas
    totais e ciclos (novos/quebrados). Tolerante a snapshots incompletos:
    só compara o que existir nos dois lados.
    """
    get_project_or_404(session, project_id)
    base_run = session.get(AnalysisRun, base)
    target_run = session.get(AnalysisRun, target)
    if base_run is None or base_run.project_id != project_id:
        raise not_found(f"Análise {base} não encontrada", code="run_not_found")
    if target_run is None or target_run.project_id != project_id:
        raise not_found(f"Análise {target} não encontrada", code="run_not_found")

    # -- arquivos (path → sha256) ------------------------------------------
    def file_map(run_id: int) -> dict[str, str]:
        rows = session.exec(
            select(FileMeta.path, FileMeta.sha256).where(FileMeta.run_id == run_id)
        ).all()
        return {path: sha for path, sha in rows}

    base_files, target_files = file_map(base), file_map(target)
    added_files = sorted(set(target_files) - set(base_files))
    removed_files = sorted(set(base_files) - set(target_files))
    modified_files = [
        {"path": path, "base_sha256": base_files[path], "target_sha256": target_files[path]}
        for path in sorted(set(base_files) & set(target_files))
        if base_files[path] != target_files[path]
    ]

    # -- símbolos (kind:qualified_name) -------------------------------------
    def symbol_set(run_id: int) -> set[str]:
        rows = session.exec(
            select(Symbol.kind, Symbol.qualified_name).where(Symbol.run_id == run_id)
        ).all()
        return {f"{kind}:{qname}" for kind, qname in rows}

    base_symbols, target_symbols = symbol_set(base), symbol_set(target)

    # -- dependências (pares src → dst) -------------------------------------
    def dep_pairs(run_id: int) -> set[str]:
        rows = session.exec(
            select(
                Dependency.source_path,
                Dependency.target_path,
                Dependency.target_module,
            ).where(Dependency.run_id == run_id)
        ).all()
        return {
            f"{src} → {dst or module}" for src, dst, module in rows
        }

    base_deps, target_deps = dep_pairs(base), dep_pairs(target)

    # -- métricas + ciclos (snapshot; recalcula só se ausente) ---------------
    base_snapshot = _run_snapshot(session, base_run)
    target_snapshot = _run_snapshot(session, target_run)

    base_cycles = {
        _cycle_signature(c)
        for c in base_snapshot.get("cycles", {}).get("signatures", [])
    }
    target_cycles = {
        _cycle_signature(c)
        for c in target_snapshot.get("cycles", {}).get("signatures", [])
    }

    return {
        "base": run_to_summary(base_run).model_dump(),
        "target": run_to_summary(target_run).model_dump(),
        "files": {
            "added": added_files,
            "removed": removed_files,
            "modified": modified_files,
            "unchanged": len(set(base_files) & set(target_files)) - len(modified_files),
        },
        "symbols": {
            "added": sorted(target_symbols - base_symbols),
            "removed": sorted(base_symbols - target_symbols),
        },
        "dependencies": {
            "added": sorted(target_deps - base_deps),
            "removed": sorted(base_deps - target_deps),
        },
        "metrics": _diff_metrics(base_snapshot, target_snapshot),
        "cycles": {
            "new": sorted(list(c) for c in target_cycles - base_cycles),
            "broken": sorted(list(c) for c in base_cycles - target_cycles),
            "unchanged": len(base_cycles & target_cycles),
        },
    }


@router.post("/{project_id}/analyze", response_model=RunSummary, status_code=202)
def analyze_project(
    project_id: int,
    payload: AnalyzeRequest | None = None,  # corpo opcional
    session: Session = Depends(get_session),
) -> RunSummary:
    """Dispara uma análise em background (responde imediatamente)."""
    project = get_project_or_404(session, project_id)
    root = Path(project.path)
    if not root.is_dir():
        raise not_found(
            f"O diretório do projeto não existe mais: {root}",
            code="project_path_missing",
        )

    running = active_run(session, project_id)
    if running is not None:
        # evita duas gravações concorrentes sobre o mesmo projeto
        if is_running(running.id or 0) or running.state == RunState.PENDING.value:
            raise conflict(
                f"Já existe uma análise em execução (run {running.id}).",
                code="analysis_running",
            )
        # run órfã (thread morreu sem finalizar) → destrava
        HUB.publish(
            running.id or 0,
            state=RunState.FAILED.value,
            stage="failed",
            error="Execução interrompida",
        )
        running.state = RunState.FAILED.value
        running.stage = "failed"
        running.error = "Execução interrompida"
        session.add(running)
        session.commit()

    run = AnalysisRun(
        project_id=project_id,
        state=RunState.PENDING.value,
        stage="queued",
        message="Aguardando execução",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    HUB.publish(
        run.id or 0,
        state=RunState.PENDING.value,
        stage="queued",
        progress=0.0,
        message="Aguardando execução",
        files_total=0,
        files_processed=0,
        files_failed=0,
        error="",
    )
    start_run(run.id or 0)
    return run_to_summary(run)


@router.get("/{project_id}/analysis/{run_id}", response_model=RunSummary)
def project_run_status(
    project_id: int,
    run_id: int,
    session: Session = Depends(get_session),
) -> RunSummary:
    """Alias de status da análise já pertencente ao projeto."""
    get_project_or_404(session, project_id)
    run = session.get(AnalysisRun, run_id)
    if run is None or run.project_id != project_id:
        raise not_found(f"Análise {run_id} não encontrada", code="run_not_found")
    return run_to_summary(run)


@router.get("/{project_id}/latest", response_model=RunSummary | None)
def project_latest(
    project_id: int, session: Session = Depends(get_session)
) -> RunSummary | None:
    """Última análise do projeto (ou ``null``)."""
    get_project_or_404(session, project_id)
    run = latest_run(session, project_id)
    return run_to_summary(run) if run else None
