"""Orquestração da análise: descoberta → parse → resolução → métricas.

A execução roda em uma thread em background (a API nunca bloqueia) e publica
progresso em memória — o endpoint SSE apenas observa esse hub.

Consistência: os registros derivados são montados em memória e gravados em
**uma única transação** ao final, de modo que uma análise só aparece completa
no banco quando termina com sucesso.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_engine
from ..models import (
    AnalysisRun,
    AppSetting,
    Dependency,
    DependencyClass,
    FileMeta,
    Metric,
    Project,
    RunState,
    Symbol,
)
from ..security import DiscoveryLimits, ExclusionRules, SecurityError
from .discovery import DiscoveryResult, read_text_limited, sha256_of, walk_project
from .metrics import ensure_run_metrics
from .python_analyzer import FileAnalysis, analyze_python_source
from .resolver import ImportResolver, build_module_index

# ---------------------------------------------------------------------------
# Hub de progresso (memória, thread-safe) — alimenta o SSE
# ---------------------------------------------------------------------------


@dataclass
class _Progress:
    run_id: int
    state: str = RunState.PENDING.value
    progress: float = 0.0
    stage: str = "queued"
    files_total: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    symbols_count: int = 0
    dependencies_count: int = 0
    message: str = ""
    error: str = ""
    cancel_requested: bool = False
    version: int = 0
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "progress": round(self.progress, 2),
            "stage": self.stage,
            "files_total": self.files_total,
            "files_processed": self.files_processed,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
            "symbols_count": self.symbols_count,
            "dependencies_count": self.dependencies_count,
            "message": self.message,
            "error": self.error,
            "version": self.version,
            "updated_at": self.updated_at,
        }


class ProgressHub:
    """Registro de progresso das runs ativas, seguro entre threads."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._runs: dict[int, _Progress] = {}

    def ensure(self, run_id: int) -> _Progress:
        with self._cond:
            if run_id not in self._runs:
                self._runs[run_id] = _Progress(run_id=run_id)
            return self._runs[run_id]

    def publish(self, run_id: int, **fields: Any) -> dict[str, Any]:
        with self._cond:
            progress = self.ensure(run_id)
            for key, value in fields.items():
                setattr(progress, key, value)
            progress.version += 1
            progress.updated_at = time.time()
            self._cond.notify_all()
            return progress.as_dict()

    def snapshot(self, run_id: int) -> dict[str, Any] | None:
        with self._cond:
            progress = self._runs.get(run_id)
            return progress.as_dict() if progress else None

    def wait(self, run_id: int, since_version: int, timeout: float = 15.0) -> dict[str, Any]:
        """Bloqueia até a versão mudar (ou timeout) e devolve o snapshot."""
        with self._cond:
            progress = self._runs.get(run_id)
            if progress is None:
                return {"run_id": run_id, "version": since_version}
            deadline = time.monotonic() + timeout
            while progress.version <= since_version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            return progress.as_dict()

    def request_cancel(self, run_id: int) -> dict[str, Any]:
        with self._cond:
            progress = self.ensure(run_id)
            progress.cancel_requested = True
            progress.version += 1
            progress.updated_at = time.time()
            self._cond.notify_all()
            return progress.as_dict()

    def cancel_requested(self, run_id: int) -> bool:
        with self._cond:
            progress = self._runs.get(run_id)
            return bool(progress and progress.cancel_requested)

    def forget(self, run_id: int) -> None:
        with self._cond:
            self._runs.pop(run_id, None)

    def reset(self) -> None:
        """Descarta todo o estado em memória (testes / shutdown)."""
        with self._cond:
            self._runs.clear()


HUB = ProgressHub()

_THREADS: dict[int, threading.Thread] = {}
_THREADS_LOCK = threading.Lock()

# quantas linhas são atualizadas no banco durante a execução
_PROGRESS_FLUSH_EVERY = 0.02  # 2% de avanço


# ---------------------------------------------------------------------------
# Acumuladores
# ---------------------------------------------------------------------------


@dataclass
class _FileBundle:
    """Um arquivo analisado, pronto para persistência."""

    meta: FileMeta
    symbols: list[Symbol] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)


@dataclass
class RunArtifacts:
    """Acumuladores usados na etapa de métricas."""

    bundles: list[_FileBundle] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    complexities: list[tuple[str, float, int | None]] = field(default_factory=list)
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    class_count: int = 0
    function_count: int = 0
    method_count: int = 0
    external_count: int = 0
    confirmed_count: int = 0
    unresolved_count: int = 0
    max_complexity: int = 0
    max_complexity_path: str = ""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def execute_run(run_id: int) -> None:
    """Executa uma análise completa. Nunca levanta exceção para fora."""
    bulk: Session | None = None
    started = datetime.now(UTC)

    try:
        HUB.publish(
            run_id,
            state=RunState.RUNNING.value,
            stage="loading",
            message="Carregando projeto",
            progress=1.0,
            error="",
        )
        _update_run_row(run_id, state=RunState.RUNNING.value, stage="loading", started_at=started)

        project, root, rules, limits = _load_run(run_id)

        if not root.is_dir():
            raise RuntimeError(f"O diretório do projeto não existe mais: {root}")

        # -- 1. descoberta ---------------------------------------------------
        HUB.publish(run_id, stage="discovery", message="Descobrindo arquivos", progress=3.0)
        _update_run_row(run_id, stage="discovery")
        discovery = walk_project(root, rules, limits)
        skipped = len(discovery.skipped_too_large) + len(discovery.skipped_binary)

        HUB.publish(
            run_id,
            stage="discovery",
            files_total=len(discovery.files),
            files_skipped=skipped,
            message=f"{len(discovery.files)} arquivos elegíveis",
            progress=8.0,
        )
        if discovery.truncated:
            HUB.publish(
                run_id,
                message=(
                    f"Limite de {limits.max_files} arquivos atingido "
                    f"({len(discovery.skipped_limit)} ignorados)"
                ),
            )

        if _cancelled(run_id):
            _finish_cancelled(run_id, started)
            return

        # -- 2. índice de módulos -------------------------------------------
        HUB.publish(run_id, stage="indexing", message="Indexando módulos", progress=12.0)
        _update_run_row(run_id, stage="indexing")
        python_paths = [f.relative_path for f in discovery.files if f.is_python]
        index = build_module_index(python_paths)
        resolver = ImportResolver(index)

        # -- 3. análise arquivo a arquivo (em memória) ------------------------
        HUB.publish(
            run_id,
            stage="parsing",
            message="Analisando arquivos",
            progress=15.0,
            files_total=len(discovery.files),
        )
        _update_run_row(run_id, stage="parsing", files_total=len(discovery.files))

        artifacts = RunArtifacts()
        processed, failed = _analyze_files(
            run_id, project, discovery, index, resolver, limits, artifacts
        )

        if _cancelled(run_id):
            _finish_cancelled(run_id, started)
            return

        # -- 4. métricas ------------------------------------------------------
        HUB.publish(run_id, stage="metrics", message="Calculando métricas", progress=90.0)
        _update_run_row(run_id, stage="metrics")

        # -- 5. persistência em transação única -------------------------------
        HUB.publish(run_id, stage="persisting", message="Gravando snapshot", progress=93.0)
        bulk = Session(get_engine())
        symbols_count, deps_count, modules_count = _persist_snapshot(
            bulk, run_id, project, artifacts
        )
        _persist_metrics(bulk, run_id, project, artifacts, len(discovery.files))
        _persist_graph_metrics(bulk, run_id, project)
        bulk.commit()
        bulk.close()
        bulk = None

        HUB.publish(
            run_id,
            state=RunState.COMPLETED.value,
            stage="completed",
            progress=100.0,
            message="Análise concluída",
            files_processed=processed,
            files_failed=failed,
            files_skipped=skipped,
            symbols_count=symbols_count,
            dependencies_count=deps_count,
        )
        _update_run_row(
            run_id,
            state=RunState.COMPLETED.value,
            stage="completed",
            progress=100.0,
            message="Análise concluída",
            files_processed=processed,
            files_failed=failed,
            files_skipped=skipped,
            symbols_count=symbols_count,
            dependencies_count=deps_count,
            modules_count=modules_count,
            errors_count=len(artifacts.parse_errors),
            finished_at=datetime.now(UTC),
        )

    except Exception as exc:  # o thread nunca pode morrer em silêncio
        if bulk is not None:
            try:
                bulk.rollback()
                bulk.close()
            except Exception:  # pragma: no cover
                pass
        detail = f"{type(exc).__name__}: {exc}"
        HUB.publish(
            run_id,
            state=RunState.FAILED.value,
            stage="failed",
            message="Análise falhou",
            error=detail,
        )
        _update_run_row(
            run_id,
            state=RunState.FAILED.value,
            stage="failed",
            error=detail,
            finished_at=datetime.now(UTC),
        )
        traceback.print_exc()
    finally:
        with _THREADS_LOCK:
            _THREADS.pop(run_id, None)


def _load_run(run_id: int) -> tuple[Project, Path, ExclusionRules, DiscoveryLimits]:
    """Lê projeto + regras + limites em uma sessão curta (sem lock prolongado)."""
    settings = get_settings()
    with Session(get_engine()) as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise RuntimeError(f"AnalysisRun {run_id} não existe")
        project = session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError(f"Project {run.project_id} não existe")
        # cópia imutável dos campos necessários (a sessão será fechada)
        project = Project.model_validate(project.model_dump())

    rules = ExclusionRules.for_project(
        settings,
        extra_dirs=project.extra_excluded_dirs,
        extra_globs=project.extra_excluded_globs,
        include_hidden=project.include_hidden,
    )
    limits = DiscoveryLimits(
        max_file_size_bytes=_int_override("max_file_size_bytes", settings.max_file_size_bytes),
        max_files=_int_override("max_files", settings.max_files),
        max_depth=_int_override("max_depth", settings.max_depth),
    )
    return project, Path(project.path), rules, limits


def _analyze_files(
    run_id: int,
    project: Project,
    discovery: DiscoveryResult,
    index: Any,
    resolver: ImportResolver,
    limits: DiscoveryLimits,
    artifacts: RunArtifacts,
) -> tuple[int, int]:
    """Analisa cada arquivo descoberto; devolve (processados, falhas)."""
    total = max(1, len(discovery.files))
    processed = 0
    failed = 0
    project_id = project.id or 0
    last_flush = 0.0

    for discovered in discovery.files:
        if _cancelled(run_id):
            return processed, failed

        text, size, _truncated = read_text_limited(
            discovered.absolute_path, limits.max_file_size_bytes
        )
        if text is None:
            failed += 1
            processed += 1
            continue

        meta = FileMeta(
            run_id=run_id,
            project_id=project_id,
            path=discovered.relative_path,
            absolute_path=str(discovered.absolute_path),
            language=discovered.language,
            size_bytes=size,
            lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            sha256=sha256_of(text),
            is_python=discovered.is_python,
            is_package=discovered.is_package,
            module=index.file_to_module.get(discovered.relative_path, ""),
        )

        analysis: FileAnalysis | None = None
        if discovered.is_python:
            analysis = analyze_python_source(
                text,
                path=discovered.relative_path,
                size_bytes=size,
                sha256=meta.sha256,
            )
            meta.parse_ok = analysis.parse_ok
            meta.parse_error = analysis.parse_error
            meta.lines = analysis.lines.total
            meta.code_lines = analysis.lines.code
            meta.comment_lines = analysis.lines.comment
            meta.blank_lines = analysis.lines.blank
            if not analysis.parse_ok:
                artifacts.parse_errors.append(
                    f"{discovered.relative_path}: {analysis.parse_error}"
                )
                failed += 1

        bundle = _FileBundle(meta=meta)
        if analysis is not None:
            _build_symbols(bundle, analysis, artifacts)
            _build_dependencies(
                bundle, analysis, index, resolver, run_id, project_id, artifacts
            )
        artifacts.bundles.append(bundle)
        artifacts.total_lines += meta.lines
        artifacts.code_lines += meta.code_lines
        artifacts.comment_lines += meta.comment_lines
        artifacts.blank_lines += meta.blank_lines

        processed += 1
        fraction = processed / total
        if fraction - last_flush >= _PROGRESS_FLUSH_EVERY or processed == total:
            last_flush = fraction
            progress = 15.0 + fraction * 73.0
            HUB.publish(
                run_id,
                progress=progress,
                files_processed=processed,
                files_total=total,
                files_failed=failed,
                message=f"{processed}/{total} arquivos",
            )
            _update_run_row(
                run_id,
                progress=progress,
                files_processed=processed,
                files_total=total,
                files_failed=failed,
            )

    return processed, failed


def _build_symbols(bundle: _FileBundle, analysis: FileAnalysis, artifacts: RunArtifacts) -> None:
    """Converte ``SymbolRecord`` em linhas prontas para a transação."""
    for record in analysis.symbols:
        bundle.symbols.append(
            Symbol(
                run_id=bundle.meta.run_id,
                project_id=bundle.meta.project_id,
                file_id=None,  # preenchido após flush dos FileMeta
                name=record.name,
                qualified_name=record.qualified_name,
                kind=record.kind,
                module=bundle.meta.module,
                lineno=record.lineno,
                end_lineno=record.end_lineno,
                is_public=record.is_public,
                is_async=record.is_async,
                is_test=_is_test_name(bundle.meta.path, record.name),
                signature=record.signature,
                docstring=record.docstring,
                decorators=record.decorators,
                bases=record.bases,
                calls=record.calls,
                params_count=record.params_count,
                complexity=record.complexity,
            )
        )
        if record.kind == "class":
            artifacts.class_count += 1
        elif record.kind == "method":
            artifacts.method_count += 1
        elif record.kind == "function":
            artifacts.function_count += 1

        if record.kind in {"function", "method", "class"}:
            artifacts.complexities.append((bundle.meta.path, float(record.complexity), None))
            if record.complexity > artifacts.max_complexity:
                artifacts.max_complexity = record.complexity
                artifacts.max_complexity_path = bundle.meta.path


def _build_dependencies(
    bundle: _FileBundle,
    analysis: FileAnalysis,
    index: Any,
    resolver: ImportResolver,
    run_id: int,
    project_id: int,
    artifacts: RunArtifacts,
) -> None:
    """Resolve cada import e classifica honestamente."""
    current_module = bundle.meta.module or index.file_to_module.get(bundle.meta.path, "")
    for record in analysis.imports:
        if record.level > 0:
            resolution = resolver.resolve_relative(record, current_module)
        else:
            resolution = resolver.resolve_absolute(record)

        if resolution.classification == DependencyClass.CONFIRMED:
            artifacts.confirmed_count += 1
        elif resolution.classification == DependencyClass.EXTERNAL:
            artifacts.external_count += 1
        else:
            artifacts.unresolved_count += 1

        bundle.dependencies.append(
            Dependency(
                run_id=run_id,
                project_id=project_id,
                source_file_id=None,
                source_path=bundle.meta.path,
                source_module=current_module,
                raw=record.raw,
                module=record.module,
                level=record.level,
                names=record.names,
                target_path=resolution.target_path,
                target_module=resolution.target_module or record.module,
                classification=resolution.classification,
                confidence=resolution.confidence,
                is_star=record.is_star,
            )
        )


def _persist_snapshot(
    session: Session,
    run_id: int,
    project: Project,
    artifacts: RunArtifacts,
) -> tuple[int, int, int]:
    """Grava arquivos, símbolos e dependências em UMA transação."""
    symbols_count = 0
    deps_count = 0
    modules: set[str] = set()

    for bundle in artifacts.bundles:
        session.add(bundle.meta)
    session.flush()  # popula os ids dos FileMeta

    for bundle in artifacts.bundles:
        if bundle.meta.module:
            modules.add(bundle.meta.module)
        for symbol in bundle.symbols:
            symbol.file_id = bundle.meta.id
            session.add(symbol)
            symbols_count += 1
        for dep in bundle.dependencies:
            dep.source_file_id = bundle.meta.id
            session.add(dep)
            deps_count += 1

    return symbols_count, deps_count, len(modules)


def _persist_metrics(
    session: Session,
    run_id: int,
    project: Project,
    artifacts: RunArtifacts,
    files_scanned: int,
) -> None:
    """Grava métricas de projeto (+ complexidade por arquivo)."""
    project_id = project.id or 0
    values: dict[str, float] = {
        "files_scanned": float(files_scanned),
        "total_lines": float(artifacts.total_lines),
        "code_lines": float(artifacts.code_lines),
        "comment_lines": float(artifacts.comment_lines),
        "blank_lines": float(artifacts.blank_lines),
        "classes": float(artifacts.class_count),
        "functions": float(artifacts.function_count),
        "methods": float(artifacts.method_count),
        "parse_errors": float(len(artifacts.parse_errors)),
        "dependencies_confirmed": float(artifacts.confirmed_count),
        "dependencies_external": float(artifacts.external_count),
        "dependencies_unresolved": float(artifacts.unresolved_count),
        "max_complexity": float(artifacts.max_complexity),
    }
    if artifacts.complexities:
        values["avg_complexity"] = round(
            sum(c for _, c, _ in artifacts.complexities) / len(artifacts.complexities), 3
        )
        values["complexity_hotspots"] = float(
            len([1 for _, c, _ in artifacts.complexities if c >= 10])
        )
    else:
        values["avg_complexity"] = 0.0
        values["complexity_hotspots"] = 0.0

    for key, value in values.items():
        session.add(
            Metric(run_id=run_id, project_id=project_id, scope="project", key=key, value=value)
        )

    per_file: dict[str, list[float]] = {}
    for path, complexity, _file_id in artifacts.complexities:
        per_file.setdefault(path, []).append(complexity)
    path_to_id = {b.meta.path: b.meta.id for b in artifacts.bundles}
    for path, complexity_values in per_file.items():
        file_id = path_to_id.get(path)
        if file_id is None:
            continue
        session.add(
            Metric(
                run_id=run_id,
                project_id=project_id,
                file_id=file_id,
                scope="file",
                key="max_complexity",
                value=max(complexity_values),
            )
        )
        session.add(
            Metric(
                run_id=run_id,
                project_id=project_id,
                file_id=file_id,
                scope="file",
                key="symbols",
                value=len(complexity_values),
            )
        )


def _persist_graph_metrics(
    session: Session,
    run_id: int,
    project: Project,
) -> None:
    """Grava o snapshot de métricas do grafo + métricas por pacote.

    Roda dentro da MESMA transação da run. Qualquer falha aqui é engolida:
    métricas derivadas nunca podem derrubar uma análise que já foi parseada —
    os endpoints calculam sob demanda se o snapshot faltar.
    """
    try:
        payload = ensure_run_metrics(session, run_id, project.id or 0, persist=False)
    except Exception:  # pragma: no cover - defesa: análise não falha por métricas
        return

    project_id = project.id or 0
    for row in payload.get("coupling", []):
        for key in ("ca", "ce", "instability"):
            session.add(
                Metric(
                    run_id=run_id,
                    project_id=project_id,
                    scope="package",
                    module=str(row.get("package", "")),
                    key=key,
                    value=float(row.get(key, 0.0)),
                )
            )
    for row in payload.get("complexity", {}).get("by_package", []):
        for key in ("complexity_sum", "complexity_avg", "complexity_max"):
            session.add(
                Metric(
                    run_id=run_id,
                    project_id=project_id,
                    scope="package",
                    module=str(row.get("package", "")),
                    key=key,
                    value=float(row.get(key.replace("complexity_", ""), 0.0)),
                )
            )

    totals = payload.get("totals", {})
    summary = payload.get("coupling_summary", {})
    cycles = payload.get("cycles", {})
    project_metrics = {
        "graph_nodes": float(totals.get("nodes", 0)),
        "graph_edges": float(totals.get("edges", 0)),
        "weak_components": float(totals.get("weak_components", 0)),
        "strong_components": float(totals.get("strong_components", 0)),
        "cycles_count": float(cycles.get("count", 0)),
        "avg_instability": float(summary.get("avg_instability", 0.0)),
    }
    for key, value in project_metrics.items():
        session.add(
            Metric(run_id=run_id, project_id=project_id, scope="project", key=key, value=value)
        )


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _is_test_name(path: str, name: str) -> bool:
    """Heurística simples de teste (apenas rótulo)."""
    lowered = path.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test")
        or "/tests/" in lowered
        or lowered.startswith("tests/")
        or "/test/" in lowered
    )


def _int_override(key: str, fallback: int) -> int:
    raw = _load_settings_override(key, None)
    try:
        return fallback if raw is None else int(raw)
    except (TypeError, ValueError):
        return fallback


def _load_settings_override(key: str, fallback: Any) -> Any:
    """Lê um override persistido na tabela ``settings`` (se houver)."""
    try:
        with Session(get_engine()) as session:
            row = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
            if row is not None and row.value is not None:
                return row.value
    except Exception:  # pragma: no cover - override é opcional
        return fallback
    return fallback


def _cancelled(run_id: int) -> bool:
    return HUB.cancel_requested(run_id)


def _update_run_row(run_id: int, **fields: Any) -> None:
    """Atualiza a linha do run em uma sessão curta (commit imediato)."""
    if not fields:
        return
    try:
        with Session(get_engine()) as session:
            run = session.get(AnalysisRun, run_id)
            if run is None:
                return
            for key, value in fields.items():
                if key.startswith("_"):
                    continue
                if hasattr(run, key):
                    setattr(run, key, value)
            session.add(run)
            session.commit()
    except Exception:  # pragma: no cover - progresso nunca derruba a análise
        pass


def _finish_cancelled(run_id: int, started: datetime) -> None:
    """Marca a run como cancelada (nada foi persistido)."""
    HUB.publish(
        run_id,
        state=RunState.CANCELLED.value,
        stage="cancelled",
        message="Análise cancelada",
    )
    _update_run_row(
        run_id,
        state=RunState.CANCELLED.value,
        stage="cancelled",
        message="Análise cancelada",
        finished_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# API de disparo
# ---------------------------------------------------------------------------


def start_run(run_id: int) -> bool:
    """Dispara a análise em background. ``False`` se já estiver rodando."""
    with _THREADS_LOCK:
        existing = _THREADS.get(run_id)
        if existing is not None and existing.is_alive():
            return False
        thread = threading.Thread(
            target=execute_run,
            args=(run_id,),
            name=f"pandora-analysis-{run_id}",
            daemon=True,
        )
        _THREADS[run_id] = thread
        thread.start()
        return True


def is_running(run_id: int) -> bool:
    with _THREADS_LOCK:
        thread = _THREADS.get(run_id)
        return bool(thread and thread.is_alive())


def reset_runtime(timeout: float = 30.0) -> None:
    """Espera threads órfãs, limpa o registro e zera o hub (testes/shutdown)."""
    with _THREADS_LOCK:
        alive = [t for t in _THREADS.values() if t.is_alive()]
    for thread in alive:
        thread.join(timeout)
    with _THREADS_LOCK:
        _THREADS.clear()
    HUB.reset()


def wait_for_run(run_id: int, timeout: float = 60.0) -> bool:
    """Aguarda a thread de uma run (usado nos testes)."""
    with _THREADS_LOCK:
        thread = _THREADS.get(run_id)
    if thread is None:
        return True
    thread.join(timeout)
    return not thread.is_alive()


__all__ = [
    "HUB",
    "SecurityError",
    "execute_run",
    "is_running",
    "reset_runtime",
    "start_run",
    "wait_for_run",
]
