"""Heurísticas determinísticas do Arquiteto IA (Fase 6).

Funções **puras**: recebem o grafo (``analysis/graph.py``) e o snapshot de
métricas (``analysis/metrics.py``) e devolvem ``findings`` estruturados.
Nenhum I/O, nenhuma rede — a narrativa em linguagem natural (Ollama) é
opcional e vem depois, apenas para explicar o que já foi medido aqui.

Contrato de cada finding::

    {"type", "severity", "title", "description", "evidence", "action",
     "affected_nodes"}
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from .graph import EDGE_IMPORTS, NODE_FILE, NODE_MODULE

#: Grau total de acoplamento (arestas imports) acima do qual um módulo é
#: considerado fortemente acoplado.
COUPLING_DEGREE_THRESHOLD = 20
#: Quantidade de hotspots (top por score) considerados por finding.
HOTSPOT_LIMIT = 5
#: Mínimo de dependências de saída para um módulo ser "instável".
UNSTABLE_MIN_OUTGOING = 5
#: Relação outgoing >> incoming que caracteriza acoplamento instável.
UNSTABLE_RATIO = 3.0
#: Limite de itens de evidência por finding (descrição traz o total).
MAX_EVIDENCE = 10
#: Limite de nós afetados por finding (payload sempre serializável).
MAX_AFFECTED = 50

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

#: Só estes tipos de nó participam das heurísticas de acoplamento: nós de
#: símbolo (contains) e módulos externos/stdlib distorceriam a contagem.
_COUPLED_TYPES = frozenset({NODE_FILE, NODE_MODULE})

ACTION_CYCLE = "Quebrar o ciclo extraindo uma interface ou invertendo a dependência"
ACTION_COUPLING = "Extrair submódulo ou aplicar princípio da inversão de dependência"
ACTION_HOTSPOT = "Refatorar o arquivo para reduzir complexidade ciclomática"
ACTION_UNSTABLE = "Estabilizar a dependência ou isolar em camada própria"


def _finding(
    finding_type: str,
    severity: str,
    title: str,
    description: str,
    evidence: list[str],
    action: str,
    affected_nodes: list[str],
) -> dict[str, Any]:
    """Monta um finding com listas limitadas (payload sempre enxuto)."""
    return {
        "type": finding_type,
        "severity": severity,
        "title": title,
        "description": description,
        "evidence": evidence[:MAX_EVIDENCE],
        "action": action,
        "affected_nodes": affected_nodes[:MAX_AFFECTED],
    }


def _label(graph: nx.DiGraph, node_id: str) -> str:
    attrs = graph.nodes.get(node_id) or {}
    return str(attrs.get("label") or node_id)


def imports_degrees(graph: nx.DiGraph) -> dict[str, tuple[int, int]]:
    """``nó -> (grau_entrada, grau_saída)`` contando SÓ arestas ``imports``.

    Um passeio único nas arestas: contém acoplamento arquitetural real
    (arestas ``contains`` arquivo→símbolo não são dependência).
    """
    degrees: dict[str, tuple[int, int]] = {}
    for source, target, attrs in graph.edges(data=True):
        if attrs.get("type") != EDGE_IMPORTS:
            continue
        in_degree, out_degree = degrees.get(source, (0, 0))
        degrees[source] = (in_degree, out_degree + 1)
        in_degree, out_degree = degrees.get(target, (0, 0))
        degrees[target] = (in_degree + 1, out_degree)
    return degrees


def detect_high_coupling(
    graph: nx.DiGraph,
    *,
    threshold: int = COUPLING_DEGREE_THRESHOLD,
    degrees: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any] | None:
    """Módulos com grau total de acoplamento acima do threshold."""
    degrees = imports_degrees(graph) if degrees is None else degrees
    rows: list[tuple[str, int]] = []
    for node_id, (in_degree, out_degree) in degrees.items():
        if node_id not in graph:
            continue
        if graph.nodes[node_id].get("type") not in _COUPLED_TYPES:
            continue
        total = in_degree + out_degree
        if total > threshold:
            rows.append((node_id, total))

    if not rows:
        return None
    rows.sort(key=lambda row: (-row[1], row[0]))

    return _finding(
        "high_coupling",
        "medium",
        "Módulos com acoplamento elevado",
        f"{len(rows)} módulo(s) com grau de acoplamento total acima de {threshold} "
        f"(dependências de entrada + saída).",
        [f"{_label(graph, node_id)}: grau {total}" for node_id, total in rows],
        ACTION_COUPLING,
        [node_id for node_id, _total in rows],
    )


def detect_unstable_dependencies(
    graph: nx.DiGraph,
    *,
    min_outgoing: int = UNSTABLE_MIN_OUTGOING,
    ratio: float = UNSTABLE_RATIO,
    degrees: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any] | None:
    """Módulos com outgoing >> incoming (acoplamento instável, I ≈ 1)."""
    degrees = imports_degrees(graph) if degrees is None else degrees
    rows: list[tuple[str, int, int]] = []
    for node_id, (in_degree, out_degree) in degrees.items():
        if node_id not in graph:
            continue
        if graph.nodes[node_id].get("type") not in _COUPLED_TYPES:
            continue
        if out_degree >= min_outgoing and out_degree >= ratio * max(in_degree, 1):
            rows.append((node_id, in_degree, out_degree))

    if not rows:
        return None
    rows.sort(key=lambda row: (-row[2], row[0]))

    return _finding(
        "unstable_dependency",
        "low",
        "Dependências instáveis (saída >> entrada)",
        f"{len(rows)} módulo(s) dependem de muito mais do que são dependidos "
        f"(saída ≥ {ratio:g}× entrada e ≥ {min_outgoing} saídas) — instabilidade alta.",
        [
            f"{_label(graph, node_id)}: {out} saída(s) × {in_} entrada(s)"
            for node_id, in_, out in rows
        ],
        ACTION_UNSTABLE,
        [node_id for node_id, _in_degree, _out_degree in rows],
    )


def detect_complex_hotspots(metrics: dict[str, Any]) -> dict[str, Any] | None:
    """Top ``HOTSPOT_LIMIT`` arquivos por score de hotspot."""
    hotspots = [row for row in (metrics.get("hotspots") or []) if isinstance(row, dict)]
    hotspots.sort(key=lambda row: (-float(row.get("score") or 0.0), str(row.get("path"))))
    top = hotspots[:HOTSPOT_LIMIT]
    if not top:
        return None

    return _finding(
        "complex_hotspot",
        "medium",
        "Hotspots de complexidade e acoplamento",
        f"Top {len(top)} arquivo(s) concentram o maior score combinando complexidade, "
        "grau, intermediação e dependências de saída.",
        [
            f"{row.get('path', '?')}: score {float(row.get('score') or 0.0):.3f} "
            f"(complexidade {float((row.get('raw') or {}).get('complexity') or 0):.0f})"
            for row in top
        ],
        ACTION_HOTSPOT,
        [str(row.get("node_id") or row.get("path") or "") for row in top],
    )


def detect_import_cycles(
    metrics: dict[str, Any], graph: nx.DiGraph | None = None
) -> dict[str, Any] | None:
    """Ciclos de import entre arquivos (usa o snapshot; recalcula se ausente)."""
    info = metrics.get("cycles")
    if not isinstance(info, dict):
        if graph is None:
            return None
        from .graph import detect_cycles as detect_cycles_graph

        info = detect_cycles_graph(graph)
    if not info.get("available") or int(info.get("count") or 0) <= 0:
        return None

    signatures: list[list[str]] = [
        list(cycle) for cycle in (info.get("signatures") or info.get("cycles") or [])
    ]
    count = int(info.get("count") or len(signatures))
    truncated = bool(info.get("truncated"))
    description = f"{count} ciclo(s) de import entre arquivos (dependência circular)."
    if truncated:
        description += f" Listagem truncada: {len(signatures)} exibidos."

    affected = sorted({node_id for cycle in signatures for node_id in cycle})
    return _finding(
        "cycle",
        "high",
        "Ciclos de dependência entre arquivos",
        description,
        [" → ".join(node.split(":", 1)[-1] for node in cycle) for cycle in signatures],
        ACTION_CYCLE,
        affected,
    )


def build_findings(graph: nx.DiGraph, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Todos os findings estruturados, ordenados por severidade.

    Função pura (sem I/O): deriva tudo do grafo e do snapshot de métricas
    já em memória. Lista vazia significa "nenhum achado estrutural".
    """
    degrees = imports_degrees(graph)
    findings = [
        detect_import_cycles(metrics, graph),
        detect_high_coupling(graph, degrees=degrees),
        detect_complex_hotspots(metrics),
        detect_unstable_dependencies(graph, degrees=degrees),
    ]
    present = [finding for finding in findings if finding is not None]
    present.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["type"]))
    return present


__all__ = [
    "ACTION_COUPLING",
    "ACTION_CYCLE",
    "ACTION_HOTSPOT",
    "ACTION_UNSTABLE",
    "COUPLING_DEGREE_THRESHOLD",
    "HOTSPOT_LIMIT",
    "SEVERITY_ORDER",
    "UNSTABLE_MIN_OUTGOING",
    "UNSTABLE_RATIO",
    "build_findings",
    "detect_complex_hotspots",
    "detect_high_coupling",
    "detect_import_cycles",
    "detect_unstable_dependencies",
    "imports_degrees",
]
