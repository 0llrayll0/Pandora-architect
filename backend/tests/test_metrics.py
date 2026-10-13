"""Testes das métricas arquiteturais (Fase 2): grafo, acoplamento, cache e API."""

from __future__ import annotations

import networkx as nx
import pytest
from sqlmodel import Session, select

from app.analysis.graph import NODE_FILE, build_graph, detect_cycles
from app.analysis.metrics import (
    BETWEENNESS_EXACT_LIMIT,
    DEFAULT_HOTSPOT_WEIGHTS,
    compute_betweenness,
    compute_degrees,
    compute_hotspots,
    compute_totals,
    coupling_summary,
    ensure_run_metrics,
    package_complexity,
    package_coupling,
    top_level_package,
)
from app.db import get_engine
from app.models import Metric, RunMetricSnapshot

# ---------------------------------------------------------------------------
# Totais e graus
# ---------------------------------------------------------------------------


def test_compute_totals_counts_types_and_components(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    totals = compute_totals(build_graph(db, run_id))

    assert totals["nodes"] == 38
    assert totals["edges"] == 34
    assert totals["nodes_by_type"] == {
        "file": 10,
        "module": 10,
        "symbol": 15,
        "external": 2,
        "unresolved": 1,
    }
    assert totals["edges_by_type"] == {"contains": 25, "imports": 9}
    assert totals["weak_components"] == 5
    assert totals["strong_components"] == 37
    assert totals["largest_scc"] == 2  # ciclo cycle1 ↔ cycle2
    assert 0 < totals["density"] < 1


def test_compute_totals_on_empty_graph() -> None:
    totals = compute_totals(nx.DiGraph())
    assert totals["nodes"] == 0
    assert totals["edges"] == 0
    assert totals["weak_components"] == 0
    assert totals["largest_scc"] == 0


def test_compute_degrees_ranks_hub_files(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    degrees = compute_degrees(build_graph(db, run_id))

    # pkg_a/mod.py concentra mais arestas de entrada (main + util + contains)
    top_in = degrees["top_in"]
    assert top_in[0]["label"] == "pkg_a/mod.py"
    assert top_in[0]["in_degree"] == 3
    assert [row["in_degree"] for row in top_in] == sorted(
        (row["in_degree"] for row in top_in), reverse=True
    )
    # main.py é o hub de saída (4 imports + contains) e de grau total
    assert degrees["top_out"][0]["label"] == "main.py"
    assert degrees["top_out"][0]["out_degree"] == 6
    top_total = degrees["top_total"][0]
    assert top_total["label"] == "main.py"
    assert top_total["degree"] == top_total["in_degree"] + top_total["out_degree"] == 7
    assert 0.0 <= top_total["degree_centrality"] <= 1.0
    assert all("degree_centrality" in row for row in degrees["top_out"])


# ---------------------------------------------------------------------------
# Acoplamento (Ca/Ce/I) e complexidade por pacote
# ---------------------------------------------------------------------------


def test_package_coupling_martin_values(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    by_pkg = {row["package"]: row for row in package_coupling(build_graph(db, run_id))}

    assert by_pkg["main"]["ca"] == 0
    assert by_pkg["main"]["ce"] == 4
    assert by_pkg["main"]["instability"] == 1.0
    assert by_pkg["pkg_a"]["ca"] == 1
    assert by_pkg["pkg_a"]["ce"] == 0
    assert by_pkg["pkg_a"]["modules"] == 3
    assert by_pkg["pkg_b"]["ca"] == 1
    assert by_pkg["pkg_b"]["ce"] == 0
    assert by_pkg["cycle1"]["ca"] == 1
    assert by_pkg["cycle1"]["ce"] == 1
    assert by_pkg["cycle1"]["instability"] == 0.5
    assert by_pkg["cycle2"]["instability"] == 0.5
    assert by_pkg["broken"]["ca"] == 0 and by_pkg["broken"]["ce"] == 0


def test_coupling_summary_excludes_uncoupled_packages(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    summary = coupling_summary(package_coupling(build_graph(db, run_id)))

    assert summary["packages"] == 6
    # broken (Ca=Ce=0) fica de fora da média: 0.5+0.5+1.0+0+0 / 5 = 0.4
    assert summary["coupled_packages"] == 5
    assert summary["avg_instability"] == 0.4


def test_package_complexity_aggregates_symbols(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    complexity = package_complexity(build_graph(db, run_id))

    assert complexity["symbols"] == 6
    assert complexity["total"] == 9.0
    assert complexity["avg"] == 1.5
    assert complexity["max"] == 4.0
    by_pkg = {row["package"]: row for row in complexity["by_package"]}
    assert by_pkg["main"]["sum"] == 4.0
    assert by_pkg["pkg_a"]["sum"] == 2.0
    assert by_pkg["pkg_b"]["max"] == 1.0


def test_top_level_package() -> None:
    assert top_level_package("pkg.sub.mod") == "pkg"
    assert top_level_package("main") == "main"
    assert top_level_package("") == ""


# ---------------------------------------------------------------------------
# Intermediação com limite (exata vs estimada)
# ---------------------------------------------------------------------------


def test_betweenness_is_exact_on_small_graph(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    values, estimated, sample_size = compute_betweenness(build_graph(db, run_id))

    assert estimated is False
    assert sample_size == 38 <= BETWEENNESS_EXACT_LIMIT
    assert values  # ao menos um valor calculado


def test_betweenness_is_estimated_above_limit() -> None:
    n = BETWEENNESS_EXACT_LIMIT + 100  # acima do limite, obriga amostragem
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(range(n))
    graph.add_edges_from((i, i + 1) for i in range(n - 1))  # cadeia sparse

    values, estimated, sample_size = compute_betweenness(graph)

    assert estimated is True
    assert 0 < sample_size <= 500
    assert len(values) == n
    # amostragem round-robin é determinística: repetir dá o mesmíssimo resultado
    again, estimated_again, sample_again = compute_betweenness(graph)
    assert (estimated_again, sample_again) == (estimated, sample_size)
    assert values == again


# ---------------------------------------------------------------------------
# Hotspots explicáveis
# ---------------------------------------------------------------------------


def test_hotspot_weights_sum_to_one_and_expose_components(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)
    betweenness, _, _ = compute_betweenness(graph)
    hotspots, weights = compute_hotspots(graph, betweenness)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights == DEFAULT_HOTSPOT_WEIGHTS
    scores = [row["score"] for row in hotspots]
    assert scores == sorted(scores, reverse=True)  # ordenado desc
    assert hotspots[0]["path"] == "main.py"
    assert hotspots[0]["score"] == 1.0  # máximo em todos os componentes
    for row in hotspots:
        for component in row["components"].values():
            assert 0.0 <= component <= 1.0
        recomputed = sum(
            row["components"][key] * weights[key] for key in weights
        )
        assert row["score"] == pytest.approx(recomputed, abs=1e-4)


def test_hotspots_score_is_weighted_dot_product(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)
    betweenness, _, _ = compute_betweenness(graph)
    hotspots, weights = compute_hotspots(graph, betweenness)
    main = next(row for row in hotspots if row["path"] == "main.py")

    assert main["raw"]["complexity"] == 4.0
    assert main["raw"]["degree"] == 7.0
    assert main["raw"]["outgoing"] == 4.0
    assert sum(weights.values()) == pytest.approx(1.0)


def test_hotspots_on_graph_without_files_returns_empty() -> None:
    graph = nx.DiGraph()
    graph.add_node("module:solo", type="module", module="solo")
    hotspots, weights = compute_hotspots(graph, {})
    assert hotspots == []
    assert sum(weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Ciclos: caminho, confiança e limites
# ---------------------------------------------------------------------------


def test_detect_cycles_details_include_path_and_confidence(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    result = detect_cycles(build_graph(db, run_id))

    assert result["available"] is True
    assert result["truncated"] is False
    assert result["cycles"] == [["file:cycle1.py", "file:cycle2.py"]]
    detail = result["details"][0]
    assert detail["size"] == 2
    assert [node["label"] for node in detail["nodes"]] == ["cycle1.py", "cycle2.py"]
    assert [edge["source"] for edge in detail["path"]] == [
        "file:cycle1.py",
        "file:cycle2.py",
    ]
    assert all(edge["classification"] == "confirmed" for edge in detail["path"])
    assert detail["confidence"] == "high"
    assert detail["min_edge_confidence"] == 1.0


def _synthetic_cycle_graph(*pairs: int) -> nx.DiGraph:
    """Grafo com ciclos de 2 nós (par → par), todos nós de arquivo."""
    graph: nx.DiGraph = nx.DiGraph()
    for a, b in pairs:
        graph.add_node(a, type=NODE_FILE, label=f"{a}.py", path=f"{a}.py")
        graph.add_node(b, type=NODE_FILE, label=f"{b}.py", path=f"{b}.py")
        graph.add_edge(a, b, type="imports", classification="confirmed", confidence=1.0)
        graph.add_edge(b, a, type="imports", classification="confirmed", confidence=1.0)
    return graph


def test_detect_cycles_truncates_at_max_cycles() -> None:
    graph = _synthetic_cycle_graph((1, 2), (3, 4), (5, 6))

    result = detect_cycles(graph, max_cycles=2)

    assert result["truncated"] is True
    assert result["count"] == 2
    assert len(result["cycles"]) == 2


def test_detect_cycles_skips_cycles_above_max_size() -> None:
    graph = nx.DiGraph()
    for node in ("a", "b", "c", "d"):
        graph.add_node(node, type=NODE_FILE, label=f"{node}.py", path=f"{node}.py")
    graph.add_edge("a", "b", type="imports", classification="confirmed", confidence=1.0)
    graph.add_edge("b", "c", type="imports", classification="confirmed", confidence=1.0)
    graph.add_edge("c", "d", type="imports", classification="confirmed", confidence=1.0)
    graph.add_edge("d", "a", type="imports", classification="confirmed", confidence=1.0)

    result = detect_cycles(graph, max_cycle_size=3)

    assert result["available"] is True
    assert result["count"] == 0
    assert result["cycles"] == []


def test_detect_cycles_marks_low_confidence_when_inferred(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)
    # degrada a aresta de volta para "inferred" (ex.: alvo não instalado)
    graph.edges["file:cycle2.py", "file:cycle1.py"]["classification"] = "unresolved"
    graph.edges["file:cycle2.py", "file:cycle1.py"]["confidence"] = 0.5

    detail = detect_cycles(graph)["details"][0]

    assert detail["confidence"] == "low"
    assert detail["min_edge_confidence"] == 0.5


# ---------------------------------------------------------------------------
# Cache por run (RunMetricSnapshot)
# ---------------------------------------------------------------------------


def test_ensure_run_metrics_persists_once_and_caches(
    analyzed_project, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run_id = analyzed_project

    payload = ensure_run_metrics(db, run_id, project.id or 0, persist=True)
    rows = db.exec(select(RunMetricSnapshot)).all()
    assert len(rows) == 1
    assert rows[0].run_id == run_id

    # segundo acesso lê o cache — o cálculo nunca roda de novo
    def _boom(*_args, **_kwargs):  # pragma: no cover - só falha se chamado
        raise AssertionError("recalculou em vez de usar o cache")

    monkeypatch.setattr("app.analysis.metrics.compute_run_metrics", _boom)
    cached = ensure_run_metrics(db, run_id, project.id or 0)
    assert cached["computed_at"] == payload["computed_at"]
    assert cached["totals"]["nodes"] == payload["totals"]["nodes"]


def test_ensure_run_metrics_without_persist_defers_commit(
    make_project, make_run, sample_project
) -> None:
    """``persist=False`` só enfileira a linha: o commit é do chamador."""
    project = make_project(sample_project)
    run_id = make_run(project)  # run pendente → sem snapshot prévio

    with Session(get_engine()) as worker:
        payload = ensure_run_metrics(worker, run_id, project.id or 0, persist=False)
        assert payload["run_id"] == run_id

        # outra sessão não enxerga a linha enquanto não houver commit
        with Session(get_engine()) as observer:
            assert observer.exec(select(RunMetricSnapshot)).all() == []

        worker.commit()
        with Session(get_engine()) as observer:
            rows = observer.exec(
                select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
            ).all()
            assert len(rows) == 1
            assert rows[0].payload["totals"]["nodes"] == 0  # run sem dados ainda


def test_pipeline_persists_graph_metrics_and_package_rows(analyzed_project, db) -> None:
    _project, run_id = analyzed_project

    snapshot = db.exec(
        select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
    ).one()
    assert snapshot.payload["totals"]["nodes"] == 38
    assert snapshot.payload["cycles"]["count"] == 1
    assert snapshot.payload["coupling_summary"]["avg_instability"] == 0.4

    package_metrics = db.exec(
        select(Metric).where(Metric.run_id == run_id, Metric.scope == "package")
    ).all()
    ca_by_module = {
        row.module: row.value for row in package_metrics if row.key == "ca"
    }
    assert ca_by_module["pkg_a"] == 1.0
    assert ca_by_module["cycle1"] == 1.0

    project_keys = {
        row.key
        for row in db.exec(
            select(Metric).where(Metric.run_id == run_id, Metric.scope == "project")
        ).all()
    }
    assert {"avg_instability", "graph_nodes", "graph_edges", "cycles_count"} <= project_keys


# ---------------------------------------------------------------------------
# Endpoints novos
# ---------------------------------------------------------------------------


def _analyze(client, sample_project) -> tuple[int, int]:
    project = client.post("/api/projects", json={"name": "demo", "path": str(sample_project)})
    pid = project.json()["id"]
    rid = client.post(f"/api/projects/{pid}/analyze", json={}).json()["id"]
    from app.analysis.pipeline import wait_for_run

    assert wait_for_run(rid) is True
    return pid, rid


def test_metrics_endpoint_exposes_graph_section(client, sample_project) -> None:
    _pid, rid = _analyze(client, sample_project)
    body = client.get(f"/api/analysis/runs/{rid}/metrics").json()

    assert body["project"]["max_complexity"] == 4.0  # contrato original intacto
    graph = body["graph"]
    assert graph["totals"]["nodes"] == 38
    assert graph["coupling"][0]["package"]
    assert graph["complexity"]["total"] == 9.0
    assert graph["cycles"]["count"] == 1
    assert graph["degrees"]["top_total"][0]["label"] == "main.py"


def test_hotspots_endpoint_shape_order_and_limit(client, sample_project) -> None:
    _pid, rid = _analyze(client, sample_project)
    body = client.get(f"/api/analysis/runs/{rid}/hotspots").json()

    assert body["run_id"] == rid
    assert body["note"] == "indicador para investigação, não defeito comprovado"
    assert sum(body["weights"].values()) == pytest.approx(1.0)
    assert body["betweenness_estimated"] is False
    assert body["total"] >= 1
    assert body["limit"] == 25
    scores = [row["score"] for row in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert body["items"][0]["path"] == "main.py"
    assert "components" in body["items"][0]

    limited = client.get(
        f"/api/analysis/runs/{rid}/hotspots", params={"limit": 2}
    ).json()
    assert len(limited["items"]) == 2
    assert limited["limit"] == 2


def test_hotspots_endpoint_404_and_invalid_limit(client) -> None:
    assert client.get("/api/analysis/runs/9999/hotspots").status_code == 404
    assert (
        client.get("/api/analysis/runs/1/hotspots", params={"limit": 0}).status_code
        in (404, 422)
    )


def test_cycles_endpoint_exposes_details_and_bounds(client, sample_project) -> None:
    _pid, rid = _analyze(client, sample_project)
    body = client.get(f"/api/graph/{rid}/cycles").json()

    assert body["count"] == 1
    detail = body["details"][0]
    assert detail["confidence"] == "high"
    assert detail["size"] == 2
    assert detail["path"][0]["source"] == "file:cycle1.py"

    bounded = client.get(
        f"/api/graph/{rid}/cycles", params={"max_cycles": 1, "max_cycle_size": 2}
    ).json()
    assert bounded["count"] == 1
    assert bounded["truncated"] is False


def test_analyses_endpoint_summarizes_graph(client, sample_project) -> None:
    pid, rid = _analyze(client, sample_project)
    body = client.get(f"/api/projects/{pid}/analyses").json()

    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == rid
    assert item["graph"]["nodes"] == 38
    assert item["graph"]["cycles"] == 1
    assert item["graph"]["avg_instability"] == 0.4
    assert item["graph"]["top_hotspot"]["path"] == "main.py"


def test_analyses_endpoint_without_snapshot_reports_null(
    client, make_project, make_run, sample_project
) -> None:
    project = make_project(sample_project)
    make_run(project)  # run nunca analisada → sem snapshot
    body = client.get(f"/api/projects/{project.id}/analyses").json()

    assert body["total"] == 1
    assert body["items"][0]["graph"] is None


def test_compare_identical_runs_reports_no_changes(
    client, sample_project, make_project, run_pipeline
) -> None:
    project = make_project(sample_project)
    base = run_pipeline(project)
    target = run_pipeline(project)  # mesmo conteúdo, hash idênticos

    body = client.get(
        f"/api/projects/{project.id}/compare", params={"base": base, "target": target}
    ).json()

    assert body["files"]["added"] == []
    assert body["files"]["removed"] == []
    assert body["files"]["modified"] == []
    assert body["symbols"]["added"] == []
    assert body["symbols"]["removed"] == []
    assert body["dependencies"]["added"] == []
    assert body["metrics"]["nodes"] == {"base": 38, "target": 38, "delta": 0}
    assert body["metrics"]["avg_instability"]["delta"] == 0.0
    assert body["cycles"]["new"] == []
    assert body["cycles"]["broken"] == []
    assert body["cycles"]["unchanged"] == 1


def test_compare_rejects_unknown_and_foreign_runs(
    client, sample_project, make_project, run_pipeline
) -> None:
    project = make_project(sample_project, name="one")
    other = make_project(sample_project, name="two")
    base = run_pipeline(project)
    foreign = run_pipeline(other)

    unknown = client.get(
        f"/api/projects/{project.id}/compare", params={"base": 9999, "target": base}
    )
    assert unknown.status_code == 404

    swapped = client.get(
        f"/api/projects/{project.id}/compare",
        params={"base": base, "target": foreign},
    )
    assert swapped.status_code == 404
    assert swapped.json()["code"] == "run_not_found"


def test_endpoints_404_for_unknown_run(client) -> None:
    assert client.get("/api/analysis/runs/9999/metrics").status_code == 404
    assert client.get("/api/graph/9999/cycles").status_code == 404


def test_delete_project_cascades_snapshot_rows(
    client, sample_project, make_project, run_pipeline, db
) -> None:
    project = make_project(sample_project)
    run_id = run_pipeline(project)
    assert db.exec(
        select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
    ).one()

    resp = client.delete(f"/api/projects/{project.id}")
    assert resp.status_code == 204

    remaining = db.exec(
        select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
    ).all()
    assert remaining == []


def test_engine_binding_matches_session(analyzed_project, db) -> None:
    """Guarda contra sessão/orphan: o cache vive no mesmo engine dos testes."""
    project, run_id = analyzed_project
    ensure_run_metrics(db, run_id, project.id or 0, persist=True)
    with Session(get_engine()) as fresh:
        rows = fresh.exec(
            select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].payload["schema"] >= 1
