"""Métricas arquiteturais sobre o grafo NetworkX (Fase 2).

Funções puras sobre o grafo construído em ``analysis/graph.py``:

- totais por tipo de nó/aresta, componentes fracos e fortes (SCC);
- grau entrada/saída e centralidade de grau (top-N exportável);
- centralidade de intermediação COM limite: exata até
  ``BETWEENNESS_EXACT_LIMIT`` nós; acima disso, amostragem determinística
  (round-robin a cada k-ésimo nó) marcando ``estimated=True`` — nunca se
  promete exatidade inexistente;
- acoplamento por pacote top-level (Ca/Ce estilo Robert C. Martin
  simplificado → instabilidade I = Ce/(Ca+Ce));
- complexidade aproximada agregada por pacote;
- hotspots explicáveis por arquivo (componentes individuais + pesos).

O cache por run vive em ``RunMetricSnapshot`` (tabela ``run_metrics``);
``ensure_run_metrics`` só recalcula quando o snapshot está ausente.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import networkx as nx
from sqlmodel import Session, select

from ..models import RunMetricSnapshot
from .graph import (
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    NODE_FILE,
    build_graph,
    detect_cycles,
)

# --------------------------------------------------------------------------
# Limites de proteção (grafos grandes nunca travam a API)
# --------------------------------------------------------------------------

#: Até esta quantidade de nós a intermediação é exata.
BETWEENNESS_EXACT_LIMIT = 1500
#: Tamanho alvo da amostra round-robin quando o grafo excede o limite.
BETWEENNESS_SAMPLE_SIZE = 500
#: Máximo de hotspots retidos no snapshot (o endpoint aplica o limit pedido).
MAX_HOTSPOTS_IN_SNAPSHOT = 500

#: Pesos default do score de hotspot (soma = 1.0).
DEFAULT_HOTSPOT_WEIGHTS: dict[str, float] = {
    "complexity": 0.35,
    "degree": 0.25,
    "betweenness": 0.25,
    "outgoing": 0.15,
}

#: Símbolos que carregam complexidade ciclomática relevante.
_COMPLEXITY_KINDS = frozenset({"function", "method", "class"})

SNAPSHOT_SCHEMA = 1


def top_level_package(module: str) -> str:
    """Pacote top-level de um módulo dotted (``pkg.mod`` → ``pkg``)."""
    return module.split(".", 1)[0] if module else ""


# --------------------------------------------------------------------------
# Totais, componentes e graus
# --------------------------------------------------------------------------


def compute_totals(graph: nx.DiGraph) -> dict[str, Any]:
    """Totais por tipo + componentes conexos (fracos) e fortemente conectados."""
    nodes_by_type: dict[str, int] = {}
    for _, attrs in graph.nodes(data=True):
        kind = str(attrs.get("type", "unknown"))
        nodes_by_type[kind] = nodes_by_type.get(kind, 0) + 1

    edges_by_type: dict[str, int] = {}
    for _, _, attrs in graph.edges(data=True):
        kind = str(attrs.get("type", "unknown"))
        edges_by_type[kind] = edges_by_type.get(kind, 0) + 1

    if graph.number_of_nodes() == 0:
        return {
            "nodes": 0,
            "edges": 0,
            "nodes_by_type": {},
            "edges_by_type": {},
            "density": 0.0,
            "weak_components": 0,
            "strong_components": 0,
            "largest_scc": 0,
        }

    weak = list(nx.weakly_connected_components(graph))
    strong = list(nx.strongly_connected_components(graph))
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "nodes_by_type": nodes_by_type,
        "edges_by_type": edges_by_type,
        "density": round(nx.density(graph), 6),
        "weak_components": len(weak),
        "strong_components": len(strong),
        "largest_scc": max((len(c) for c in strong), default=0),
    }


def compute_degrees(graph: nx.DiGraph, *, top_n: int = 50) -> dict[str, Any]:
    """Grau entrada/saída + centralidade de grau, nos top-N nós por soma."""
    n = graph.number_of_nodes()
    if n == 0:
        return {"top_in": [], "top_out": [], "top_total": [], "top_n": top_n}

    degree_centralities = nx.degree_centrality(graph)

    def entry(node_id: str) -> dict[str, Any]:
        attrs = graph.nodes[node_id]
        in_deg = graph.in_degree(node_id)
        out_deg = graph.out_degree(node_id)
        return {
            "id": node_id,
            "label": attrs.get("label", node_id),
            "type": attrs.get("type", ""),
            "in_degree": in_deg,
            "out_degree": out_deg,
            "degree": in_deg + out_deg,
            "degree_centrality": round(float(degree_centralities.get(node_id, 0.0)), 6),
        }

    nodes = list(graph.nodes())
    top_in = sorted(nodes, key=lambda n_id: (-graph.in_degree(n_id), n_id))[:top_n]
    top_out = sorted(nodes, key=lambda n_id: (-graph.out_degree(n_id), n_id))[:top_n]
    top_total = sorted(
        nodes, key=lambda n_id: (-(graph.in_degree(n_id) + graph.out_degree(n_id)), n_id)
    )[:top_n]

    return {
        "top_in": [entry(n_id) for n_id in top_in],
        "top_out": [entry(n_id) for n_id in top_out],
        "top_total": [entry(n_id) for n_id in top_total],
        "top_n": top_n,
    }


def compute_betweenness(
    graph: nx.DiGraph,
    *,
    exact_limit: int = BETWEENNESS_EXACT_LIMIT,
    sample_size: int = BETWEENNESS_SAMPLE_SIZE,
) -> tuple[dict[str, float], bool, int]:
    """Centralidade de intermediação com proteção de custo.

    Retorna ``(valores, estimated, nós_amostrados)``. Exata até ``exact_limit``
    nós; acima, amostragem round-robin determinística (nós ordenados, cada
    k-ésimo) via ``betweenness_centrality_subset`` — o payload sempre expõe
    ``estimated`` para o cliente saber que o número é uma aproximação.
    """
    n = graph.number_of_nodes()
    if n == 0:
        return {}, False, 0
    if n <= exact_limit:
        values = nx.betweenness_centrality(graph, normalized=True)
        return values, False, n

    nodes = sorted(graph.nodes())  # ordem estável → amostra determinística
    step = max(1, n // sample_size)
    sample = nodes[::step][:sample_size]
    values = nx.betweenness_centrality_subset(
        graph, sources=sample, targets=sample, normalized=True
    )
    return values, True, len(sample)


# --------------------------------------------------------------------------
# Acoplamento por pacote (Ca/Ce → instabilidade de R. C. Martin)
# --------------------------------------------------------------------------


def package_coupling(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """Ca/Ce por pacote top-level a partir das arestas ``imports``.

    - Ca (afferent): dependências que ENTRAM no pacote vindas de outros pacotes;
    - Ce (efferent): dependências que SAEM do pacote para fora dele;
    - I = Ce/(Ca+Ce) quando Ca+Ce > 0 (0 sem dependências).

    Só pacotes com ao menos um arquivo no projeto entram na lista.
    """
    packages_with_files: set[str] = set()
    for _, attrs in graph.nodes(data=True):
        if attrs.get("type") == NODE_FILE:
            pkg = top_level_package(str(attrs.get("module") or ""))
            if pkg:
                packages_with_files.add(pkg)

    ca: dict[str, int] = {pkg: 0 for pkg in packages_with_files}
    ce: dict[str, int] = {pkg: 0 for pkg in packages_with_files}

    for source, target, attrs in graph.edges(data=True):
        if attrs.get("type") != EDGE_IMPORTS:
            continue
        src_pkg = top_level_package(str(graph.nodes[source].get("module") or ""))
        dst_pkg = top_level_package(str(graph.nodes[target].get("module") or ""))
        if not src_pkg or not dst_pkg or src_pkg == dst_pkg:
            continue
        if src_pkg in ce:
            ce[src_pkg] += 1
        else:  # nó de arquivo sem módulo registrado — não conta
            continue
        if dst_pkg in ca:
            ca[dst_pkg] += 1

    rows: list[dict[str, Any]] = []
    for pkg in sorted(packages_with_files):
        c_a, c_e = ca[pkg], ce[pkg]
        total = c_a + c_e
        rows.append(
            {
                "package": pkg,
                "ca": c_a,
                "ce": c_e,
                "instability": round(c_e / total, 4) if total else 0.0,
                "modules": sum(
                    1
                    for _n, a in graph.nodes(data=True)
                    if a.get("type") == NODE_FILE
                    and top_level_package(str(a.get("module") or "")) == pkg
                ),
            }
        )
    return rows


def coupling_summary(coupling: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumo do acoplamento: instabilidade média só sobre pacotes acoplados."""
    coupled = [row["instability"] for row in coupling if (row["ca"] + row["ce"]) > 0]
    avg = round(sum(coupled) / len(coupled), 4) if coupled else 0.0
    return {
        "packages": len(coupling),
        "coupled_packages": len(coupled),
        "avg_instability": avg,
    }


# --------------------------------------------------------------------------
# Complexidade por pacote
# --------------------------------------------------------------------------


def package_complexity(graph: nx.DiGraph) -> dict[str, Any]:
    """Complexidade aproximada (símbolos function/method/class) por pacote."""
    per_package: dict[str, list[float]] = {}
    for _, attrs in graph.nodes(data=True):
        if attrs.get("type") != "symbol":
            continue
        if str(attrs.get("kind", "")) not in _COMPLEXITY_KINDS:
            continue
        pkg = top_level_package(str(attrs.get("module") or ""))
        if not pkg:
            continue
        per_package.setdefault(pkg, []).append(float(attrs.get("complexity") or 0.0))

    by_package: list[dict[str, Any]] = []
    all_values: list[float] = []
    for pkg in sorted(per_package):
        values = per_package[pkg]
        all_values.extend(values)
        by_package.append(
            {
                "package": pkg,
                "symbols": len(values),
                "sum": round(sum(values), 3),
                "avg": round(sum(values) / len(values), 3),
                "max": round(max(values), 3),
            }
        )

    total = round(sum(all_values), 3)
    return {
        "by_package": by_package,
        "symbols": len(all_values),
        "total": total,
        "avg": round(total / len(all_values), 3) if all_values else 0.0,
        "max": round(max(all_values), 3) if all_values else 0.0,
    }


# --------------------------------------------------------------------------
# Hotspots explicáveis por arquivo
# --------------------------------------------------------------------------


def compute_hotspots(
    graph: nx.DiGraph,
    betweenness: dict[str, float],
    *,
    weights: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Score explicável por arquivo. Componentes 0-1 + pesos sempre visíveis.

    Componentes: (a) soma da complexidade dos símbolos do arquivo,
    (b) grau total (in+out), (c) intermediação, (d) dependências de saída.
    Cada componente é normalizado pelo máximo entre os arquivos.
    """
    active_weights = dict(DEFAULT_HOTSPOT_WEIGHTS if weights is None else weights)
    if sum(active_weights.values()) <= 0:
        active_weights = dict(DEFAULT_HOTSPOT_WEIGHTS)

    raw: dict[str, dict[str, float]] = {}
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("type") != NODE_FILE:
            continue
        complexity = 0.0
        outgoing = 0
        for _, target, edge_attrs in graph.out_edges(node_id, data=True):
            if edge_attrs.get("type") == EDGE_CONTAINS:
                t_attrs = graph.nodes[target]
                if str(t_attrs.get("kind", "")) in _COMPLEXITY_KINDS:
                    complexity += float(t_attrs.get("complexity") or 0.0)
            elif edge_attrs.get("type") == EDGE_IMPORTS:
                outgoing += 1
        raw[node_id] = {
            "complexity": complexity,
            "degree": float(graph.in_degree(node_id) + graph.out_degree(node_id)),
            "betweenness": float(betweenness.get(node_id, 0.0)),
            "outgoing": float(outgoing),
        }

    maxima = {
        key: max((values[key] for values in raw.values()), default=0.0)
        for key in active_weights
    }

    hotspots: list[dict[str, Any]] = []
    for node_id, values in raw.items():
        components = {
            key: (
                round(values[key] / maxima[key], 4) if maxima.get(key, 0.0) > 0 else 0.0
            )
            for key in active_weights
        }
        score = round(sum(components[k] * active_weights[k] for k in active_weights), 4)
        hotspots.append(
            {
                "path": str(graph.nodes[node_id].get("path") or node_id),
                "node_id": node_id,
                "score": score,
                "components": components,
                "raw": {k: round(v, 4) for k, v in values.items()},
            }
        )

    hotspots.sort(key=lambda h: (-h["score"], h["path"]))
    return hotspots[:MAX_HOTSPOTS_IN_SNAPSHOT], active_weights


# --------------------------------------------------------------------------
# Snapshot completo + cache por run
# --------------------------------------------------------------------------


def compute_run_metrics(graph: nx.DiGraph) -> dict[str, Any]:
    """Todas as métricas da run em um único payload serializável."""
    totals = compute_totals(graph)
    degrees = compute_degrees(graph)
    betweenness_values, estimated, sample_size = compute_betweenness(graph)
    betweenness_top = sorted(
        (
            {
                "id": node_id,
                "label": graph.nodes[node_id].get("label", node_id),
                "value": round(float(value), 6),
            }
            for node_id, value in betweenness_values.items()
        ),
        key=lambda row: (-row["value"], row["id"]),
    )[:25]
    coupling = package_coupling(graph)
    complexity = package_complexity(graph)
    hotspots, weights = compute_hotspots(graph, betweenness_values)
    cycles = detect_cycles(graph)

    return {
        "schema": SNAPSHOT_SCHEMA,
        "computed_at": datetime.now(UTC).isoformat(),
        "totals": totals,
        "degrees": degrees,
        "betweenness": {
            "estimated": estimated,
            "sample_size": sample_size,
            "exact_limit": BETWEENNESS_EXACT_LIMIT,
            "top": betweenness_top,
        },
        "coupling": coupling,
        "coupling_summary": coupling_summary(coupling),
        "complexity": complexity,
        "hotspot_weights": weights,
        "hotspots": hotspots,
        "cycles": {
            "available": cycles["available"],
            "reason": cycles["reason"],
            "count": cycles["count"],
            "truncated": cycles.get("truncated", False),
            "signatures": cycles["cycles"],
        },
    }


def ensure_run_metrics(
    session: Session, run_id: int, project_id: int, *, persist: bool = True
) -> dict[str, Any]:
    """Lê o cache por run; calcula e (opcionalmente) persiste se ausente.

    Com ``persist=False`` o snapshot é apenas ``session.add`` — o chamador
    (pipeline) commita na mesma transação da run.
    """
    row = session.exec(
        select(RunMetricSnapshot).where(RunMetricSnapshot.run_id == run_id)
    ).first()
    if row is not None and row.payload:
        return row.payload

    graph = build_graph(session, run_id)
    payload = compute_run_metrics(graph)
    payload["run_id"] = run_id
    payload["project_id"] = project_id

    if row is not None:
        row.payload = payload
        session.add(row)
    else:
        session.add(
            RunMetricSnapshot(run_id=run_id, project_id=project_id, payload=payload)
        )
    if persist:
        session.commit()
    return payload


__all__ = [
    "BETWEENNESS_EXACT_LIMIT",
    "BETWEENNESS_SAMPLE_SIZE",
    "DEFAULT_HOTSPOT_WEIGHTS",
    "compute_betweenness",
    "compute_degrees",
    "compute_hotspots",
    "compute_run_metrics",
    "compute_totals",
    "coupling_summary",
    "ensure_run_metrics",
    "package_complexity",
    "package_coupling",
    "top_level_package",
]
