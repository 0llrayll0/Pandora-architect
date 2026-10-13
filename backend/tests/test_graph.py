"""Testes do grafo de arquitetura (NetworkX) a partir do snapshot."""

from __future__ import annotations

import networkx as nx

from app.analysis.graph import build_graph, detect_cycles, graph_payload


def test_build_graph_node_types(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)

    types = {node_id: attrs["type"] for node_id, attrs in graph.nodes(data=True)}
    assert types["file:main.py"] == "file"
    assert types["module:main"] == "module"
    assert types["symbol:function:main.main"] == "symbol"
    assert types["module:os"] == "external"
    assert types["module:pkg_a.fantasma"] == "unresolved"


def test_build_graph_contains_and_import_edges(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)

    # contains: módulo -> arquivo e arquivo -> símbolo
    assert graph.has_edge("module:main", "file:main.py")
    assert graph.has_edge("file:main.py", "symbol:function:main.main")

    # imports internos confirmados (arquivo -> arquivo)
    assert graph.has_edge("file:main.py", "file:pkg_a/mod.py")
    assert graph.has_edge("file:main.py", "file:pkg_b/service.py")
    assert graph.has_edge("file:pkg_a/util.py", "file:pkg_a/mod.py")
    assert graph.has_edge("file:pkg_b/service.py", "file:pkg_b/x.py")

    # ciclo entre arquivos (nos dois sentidos)
    assert graph.has_edge("file:cycle1.py", "file:cycle2.py")
    assert graph.has_edge("file:cycle2.py", "file:cycle1.py")

    # externo e não resolvido
    assert graph.has_edge("file:main.py", "module:os")
    assert graph.has_edge("file:pkg_a/util.py", "module:pkg_a.fantasma")

    # grafo direcionado
    assert isinstance(graph, nx.DiGraph)


def test_build_graph_counts(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)
    payload = graph_payload(graph)

    by_type = payload["counts"]["nodes_by_type"]
    assert by_type["file"] == 10
    assert by_type["module"] == 10
    assert by_type["symbol"] == 15
    assert by_type["external"] == 2  # os + requests
    assert by_type["unresolved"] == 1  # pkg_a.fantasma
    assert payload["counts"]["nodes"] == 38

    assert payload["counts"]["edges"] == 34  # 10 contains + 15 contains + 9 imports
    assert payload["counts"]["edges_by_type"]["imports"] == 9
    assert payload["counts"]["is_dag"] is False  # há ciclo
    assert 0.0 < payload["counts"]["density"] <= 1.0
    assert payload["counts"]["density"] == round(payload["counts"]["density"], 6)


def test_graph_payload_structure(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    payload = graph_payload(build_graph(db, run_id))

    assert {n["id"] for n in payload["nodes"]} >= {"file:main.py", "module:main"}
    edge = next(e for e in payload["edges"] if e["source"] == "file:main.py")
    assert "target" in edge and "type" in edge


# ---------------------------------------------------------------------------
# Ciclos
# ---------------------------------------------------------------------------


def test_detect_cycles_finds_file_cycle(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    result = detect_cycles(build_graph(db, run_id))

    assert result["available"] is True
    assert result["count"] == 1
    assert result["cycles"] == [["file:cycle1.py", "file:cycle2.py"]]
    assert result["nodes_considered"] == 10  # apenas nós de arquivo


def test_detect_cycles_respects_node_limit(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    result = detect_cycles(build_graph(db, run_id), max_nodes=0)

    assert result["available"] is False
    assert result["count"] == 0
    assert result["cycles"] == []
    assert "excede o limite" in result["reason"]


def test_detect_cycles_on_dag_returns_none(analyzed_project, db) -> None:
    _project, run_id = analyzed_project
    graph = build_graph(db, run_id)
    graph.remove_edge("file:cycle2.py", "file:cycle1.py")  # quebra o ciclo

    result = detect_cycles(graph)
    assert result["available"] is True
    assert result["count"] == 0
