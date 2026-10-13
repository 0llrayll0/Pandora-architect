"""Construção do grafo de arquitetura com NetworkX a partir do snapshot.

Nós: arquivo, módulo, símbolo (e módulos externos/não resolvidos).
Arestas: ``contains`` (módulo→arquivo, arquivo→símbolo) e
``imports`` (arquivo→arquivo, arquivo→módulo).

Fase 2 poderá acrescentar métricas avançadas sobre o mesmo grafo.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from sqlmodel import Session, select

from ..models import Dependency, FileMeta, Symbol

EDGE_IMPORTS = "imports"
EDGE_CONTAINS = "contains"

NODE_FILE = "file"
NODE_MODULE = "module"
NODE_SYMBOL = "symbol"
NODE_EXTERNAL = "external"
NODE_UNRESOLVED = "unresolved"

# Proteção contra explosão combinatorial em nx.simple_cycles
CYCLE_NODE_LIMIT = 400


def file_node_id(path: str) -> str:
    return f"file:{path}"


def module_node_id(module: str) -> str:
    return f"module:{module}"


def symbol_node_id(qname: str, kind: str) -> str:
    return f"symbol:{kind}:{qname}"


def build_graph(session: Session, run_id: int) -> nx.DiGraph:
    """Monta o MultiDiGraph simples (DiGraph) do snapshot da análise."""
    graph: nx.DiGraph = nx.DiGraph()

    files = session.exec(select(FileMeta).where(FileMeta.run_id == run_id)).all()
    symbols = session.exec(select(Symbol).where(Symbol.run_id == run_id)).all()
    deps = session.exec(select(Dependency).where(Dependency.run_id == run_id)).all()

    file_by_id: dict[int, FileMeta] = {f.id: f for f in files if f.id is not None}

    for meta in files:
        if meta.id is None:
            continue
        graph.add_node(
            file_node_id(meta.path),
            id=file_node_id(meta.path),
            type=NODE_FILE,
            label=meta.path,
            path=meta.path,
            module=meta.module,
            language=meta.language,
            lines=meta.lines,
            parse_ok=meta.parse_ok,
        )
        if meta.module:
            m_id = module_node_id(meta.module)
            graph.add_node(
                m_id,
                id=m_id,
                type=NODE_MODULE,
                label=meta.module,
                module=meta.module,
                path=meta.path,
            )
            graph.add_edge(
                m_id, file_node_id(meta.path), type=EDGE_CONTAINS, label="contains"
            )

    for sym in symbols:
        if not sym.qualified_name:
            continue
        s_id = symbol_node_id(sym.qualified_name, sym.kind)
        graph.add_node(
            s_id,
            id=s_id,
            type=NODE_SYMBOL,
            label=f"{sym.kind} {sym.name}",
            kind=sym.kind,
            name=sym.name,
            module=sym.module,
            path="",
            complexity=sym.complexity,
            lineno=sym.lineno,
        )
        # procura o arquivo de origem do símbolo
        source_path = ""
        if sym.file_id is not None and sym.file_id in file_by_id:
            source_path = file_by_id[sym.file_id].path
        elif sym.module:
            for meta in files:
                if meta.module == sym.module:
                    source_path = meta.path
                    break
        if source_path:
            graph.add_edge(
                file_node_id(source_path), s_id, type=EDGE_CONTAINS, label="contains"
            )

    for dep in deps:
        if not dep.source_path:
            continue
        source_id = file_node_id(dep.source_path)
        if not graph.has_node(source_id):
            continue

        target_id: str | None = None
        if dep.classification == "confirmed" and dep.target_path:
            target_id = file_node_id(dep.target_path)
            if not graph.has_node(target_id):
                target_id = None
            if target_id is None and dep.target_module:
                target_id = module_node_id(dep.target_module)
                graph.add_node(
                    target_id,
                    id=target_id,
                    type=NODE_MODULE,
                    label=dep.target_module,
                    module=dep.target_module,
                    path="",
                )
        elif dep.classification == "external" and dep.target_module:
            target_id = module_node_id(dep.target_module)
            if not graph.has_node(target_id):
                graph.add_node(
                    target_id,
                    id=target_id,
                    type=NODE_EXTERNAL,
                    label=dep.target_module,
                    module=dep.target_module,
                    path="",
                )
        elif dep.classification == "unresolved" and dep.target_module:
            target_id = module_node_id(dep.target_module)
            if not graph.has_node(target_id):
                graph.add_node(
                    target_id,
                    id=target_id,
                    type=NODE_UNRESOLVED,
                    label=dep.target_module,
                    module=dep.target_module,
                    path="",
                )

        if target_id and target_id != source_id:
            graph.add_edge(
                source_id,
                target_id,
                type=EDGE_IMPORTS,
                label=dep.raw or dep.module,
                classification=dep.classification,
                module=dep.module,
                confidence=dep.confidence,
            )

    return graph


def graph_payload(graph: nx.DiGraph) -> dict[str, Any]:
    """Serializa o grafo como ``{"nodes": [...], "edges": [...], "counts": {}}``."""
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        entry = dict(attrs)
        entry.setdefault("id", node_id)
        nodes.append(entry)

    edges = []
    for source, target, attrs in graph.edges(data=True):
        entry = dict(attrs)
        entry["source"] = source
        entry["target"] = target
        edges.append(entry)

    type_counts: dict[str, int] = {}
    for _, attrs in graph.nodes(data=True):
        kind = str(attrs.get("type", "unknown"))
        type_counts[kind] = type_counts.get(kind, 0) + 1

    edge_counts: dict[str, int] = {}
    for _, _, attrs in graph.edges(data=True):
        kind = str(attrs.get("type", "unknown"))
        edge_counts[kind] = edge_counts.get(kind, 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "nodes_by_type": type_counts,
            "edges_by_type": edge_counts,
            "density": round(nx.density(graph), 6) if graph.number_of_nodes() else 0.0,
            "is_dag": nx.is_directed_acyclic_graph(graph) if graph.number_of_nodes() else True,
        },
    }


def detect_cycles(
    graph: nx.DiGraph,
    *,
    max_nodes: int = CYCLE_NODE_LIMIT,
    max_cycles: int = 50,
    max_cycle_size: int = 50,
) -> dict[str, Any]:
    """Detecta ciclos entre arquivos (imports), com limites de segurança.

    O campo ``cycles`` mantém o contrato original (lista de listas de ids de
    nó). O campo ``details`` (Fase 2) expõe, para cada ciclo listado, o
    caminho completo (nós com label + arestas com classificação), o tamanho e
    a ``confidence``: ``high`` quando todas as arestas são ``confirmed``;
    ``low`` quando alguma aresta é inferred/external/unresolved (ex. externo
    não instalado, conf 0.5).
    """
    file_nodes = [n for n, a in graph.nodes(data=True) if a.get("type") == NODE_FILE]
    subgraph = graph.subgraph(file_nodes).copy()

    if subgraph.number_of_nodes() > max_nodes:
        return {
            "available": False,
            "reason": f"grafo com {subgraph.number_of_nodes()} nós excede o limite "
            f"de {max_nodes} para detecção de ciclos",
            "cycles": [],
            "details": [],
            "count": 0,
            "truncated": False,
        }

    cycles: list[list[str]] = []
    truncated = False
    try:
        for cycle in nx.simple_cycles(subgraph):
            if len(cycle) > max_cycle_size:
                continue
            cycles.append(list(cycle))
            if len(cycles) > max_cycles:  # coleta 1 extra para marcar truncamento
                truncated = True
                break
    except RecursionError:  # pragma: no cover - rede extrema
        return {
            "available": False,
            "reason": "limite de recursão atingido na detecção de ciclos",
            "cycles": [],
            "details": [],
            "count": 0,
            "truncated": False,
        }

    # normaliza cada ciclo começando pelo menor caminho (ordem canônica)
    normalized: list[list[str]] = []
    for cycle in cycles:
        if not cycle:
            continue
        pivot = cycle.index(min(cycle))
        normalized.append([*cycle[pivot:], *cycle[:pivot]])

    normalized.sort(key=lambda c: (len(c), c))
    if truncated:
        normalized = normalized[:max_cycles]

    details = [_cycle_detail(subgraph, cycle) for cycle in normalized]

    return {
        "available": True,
        "reason": "",
        "count": len(normalized),
        "cycles": normalized,
        "details": details,
        "truncated": truncated,
        "nodes_considered": subgraph.number_of_nodes(),
    }


def _cycle_detail(subgraph: nx.DiGraph, cycle: list[str]) -> dict[str, Any]:
    """Caminho completo + confidence de um ciclo (arestas do subgrafo)."""
    nodes = [
        {
            "id": node_id,
            "label": subgraph.nodes[node_id].get("label", node_id),
            "type": subgraph.nodes[node_id].get("type", ""),
            "path": subgraph.nodes[node_id].get("path", ""),
        }
        for node_id in cycle
    ]

    path: list[dict[str, Any]] = []
    confidence = "high"
    min_edge_confidence = 1.0
    for index, source in enumerate(cycle):
        target = cycle[(index + 1) % len(cycle)]
        attrs = subgraph.get_edge_data(source, target) or {}
        classification = str(attrs.get("classification") or "")
        edge_confidence = float(attrs.get("confidence") or 0.0)
        min_edge_confidence = min(min_edge_confidence, edge_confidence)
        if attrs.get("type") != EDGE_IMPORTS or classification != "confirmed":
            confidence = "low"
        path.append(
            {
                "source": source,
                "target": target,
                "classification": classification,
                "label": attrs.get("label", ""),
                "confidence": edge_confidence,
            }
        )

    return {
        "nodes": nodes,
        "path": path,
        "size": len(cycle),
        "confidence": confidence,
        "min_edge_confidence": round(min_edge_confidence, 3),
    }
