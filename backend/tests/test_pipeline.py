"""Testes do pipeline de análise (snapshot, métricas, cancel, falha)."""

from __future__ import annotations

from pathlib import Path

from app.analysis.pipeline import (
    HUB,
    execute_run,
    is_running,
    reset_runtime,
    start_run,
    wait_for_run,
)
from app.models import AnalysisRun, Dependency, FileMeta, Metric, RunState, Symbol


def _project_metrics(db, run_id: int) -> dict[str, float]:
    rows = (
        db.query(Metric)
        .filter(Metric.run_id == run_id, Metric.scope == "project")
        .all()
    )
    return {row.key: row.value for row in rows}


def test_execute_run_completes_with_expected_counts(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    db.expire_all()

    run = db.get(AnalysisRun, run_id)
    assert run is not None
    assert run.state == RunState.COMPLETED.value
    assert run.progress == 100.0
    assert run.files_total == 10
    assert run.files_processed == 10
    assert run.files_failed == 1
    assert run.errors_count == 1
    assert run.symbols_count == 15
    assert run.dependencies_count == 9
    assert run.modules_count == 10

    # snapshot de arquivos
    files = db.query(FileMeta).filter(FileMeta.run_id == run_id).all()
    assert len(files) == 10
    broken = next(f for f in files if f.path == "broken.py")
    assert broken.parse_ok is False
    assert "SyntaxError" in (broken.parse_error or "")

    # dependências por classificação
    deps = db.query(Dependency).filter(Dependency.run_id == run_id).all()
    assert len(deps) == 9
    by_class = {
        c: sum(1 for d in deps if d.classification == c)
        for c in ("confirmed", "external", "unresolved")
    }
    assert by_class == {"confirmed": 6, "external": 2, "unresolved": 1}
    resolved = {(d.source_module, d.target_module) for d in deps}
    assert ("main", "os") in resolved
    assert ("main", "requests") in resolved
    assert ("pkg_a.util", "pkg_a.fantasma") in resolved  # unresolved

    # símbolos: 9 module (broken.py falhou) + 6 funções
    symbols = db.query(Symbol).filter(Symbol.run_id == run_id).all()
    assert len(symbols) == 15
    assert sum(1 for s in symbols if s.kind == "module") == 9
    assert sum(1 for s in symbols if s.kind == "function") == 6
    main_fn = next(s for s in symbols if s.name == "main")
    assert main_fn.complexity == 4


def test_project_metrics_persisted(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    db.expire_all()
    metrics = _project_metrics(db, run_id)

    assert metrics["files_scanned"] == 10.0
    assert metrics["parse_errors"] == 1.0
    assert metrics["dependencies_confirmed"] == 6.0
    assert metrics["dependencies_external"] == 2.0
    assert metrics["dependencies_unresolved"] == 1.0
    assert metrics["functions"] == 6.0
    assert metrics["classes"] == 0.0
    assert metrics["methods"] == 0.0
    assert metrics["max_complexity"] == 4.0
    assert metrics["avg_complexity"] == 1.5
    assert metrics["total_lines"] > 0.0
    assert metrics["code_lines"] > 0.0


def test_cancel_before_execution_persists_nothing(
    sample_project: Path, make_project, make_run, db
) -> None:
    project = make_project(sample_project)
    run_id = make_run(project)

    HUB.request_cancel(run_id)
    execute_run(run_id)  # determinístico: cancela na checagem pós-discovery
    db.expire_all()

    run = db.get(AnalysisRun, run_id)
    assert run is not None
    assert run.state == RunState.CANCELLED.value
    assert run.stage == "cancelled"
    assert db.query(FileMeta).filter(FileMeta.run_id == run_id).count() == 0
    assert db.query(Symbol).filter(Symbol.run_id == run_id).count() == 0
    assert db.query(Dependency).filter(Dependency.run_id == run_id).count() == 0
    HUB.forget(run_id)


def test_execute_run_marks_failed_when_path_missing(
    tmp_path: Path, make_project, make_run, db
) -> None:
    project = make_project(tmp_path / "diretorio_que_nao_existe")
    run_id = make_run(project)

    execute_run(run_id)  # nunca levanta exceção para fora
    db.expire_all()

    run = db.get(AnalysisRun, run_id)
    assert run is not None
    assert run.state == RunState.FAILED.value
    assert run.stage == "failed"
    assert "RuntimeError" in (run.error or "")
    assert "não existe mais" in (run.error or "")


def test_start_run_background_completes(sample_project, make_project, make_run, db) -> None:
    project = make_project(sample_project)
    run_id = make_run(project)

    assert start_run(run_id) is True
    assert wait_for_run(run_id) is True

    db.expire_all()
    run = db.get(AnalysisRun, run_id)
    assert run is not None
    assert run.state == RunState.COMPLETED.value
    assert run.files_processed == 10
    assert is_running(run_id) is False


def test_wait_for_run_without_thread_returns_true(tmp_path, make_project, make_run) -> None:
    run_id = make_run(make_project(tmp_path / "x"))
    # sem thread registrada → nada a esperar
    assert wait_for_run(run_id) is True


def test_hub_snapshot_tracks_completed_run(analyzed_project) -> None:
    _project, run_id = analyzed_project
    snap = HUB.snapshot(run_id)
    assert snap is not None
    assert snap["state"] == RunState.COMPLETED.value
    assert snap["progress"] == 100.0


def test_reset_runtime_clears_hub(analyzed_project) -> None:
    _project, run_id = analyzed_project
    assert HUB.snapshot(run_id) is not None
    reset_runtime(timeout=1.0)
    assert HUB.snapshot(run_id) is None
