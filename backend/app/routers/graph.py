"""Grafo de arquitetura (NetworkX) e detecção de ciclos."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..analysis.graph import build_graph, detect_cycles, graph_payload
from ..db import get_session
from ..models import AnalysisRun
from .common import get_run_or_404

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{run_id}")
def get_graph(
    run_id: int,
    include_symbols: bool = Query(
        default=True, description="Incluir nós de símbolo (classes/funções)"
    ),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Grafo completo em JSON: ``{"nodes": [...], "edges": [...], "counts": {}}``."""
    run: AnalysisRun = get_run_or_404(session, run_id)
    graph = build_graph(session, run.id or 0)

    if not include_symbols:
        nodes_to_drop = [
            n for n, attrs in graph.nodes(data=True) if attrs.get("type") == "symbol"
        ]
        graph.remove_nodes_from(nodes_to_drop)

    payload = graph_payload(graph)
    payload["run_id"] = run.id
    payload["project_id"] = run.project_id
    return payload


@router.get("/{run_id}/cycles")
def cycles(
    run_id: int,
    max_cycles: int = Query(
        default=50, ge=1, le=500, description="Máximo de ciclos listados"
    ),
    max_cycle_size: int = Query(
        default=50, ge=2, le=200, description="Máximo de nós por ciclo"
    ),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Ciclos de import entre arquivos (``nx.simple_cycles`` com limite).

    Além da lista ``cycles`` (ids de nós — contrato original), expõe
    ``details`` com caminho completo e ``confidence`` por ciclo
    (high = todas as arestas confirmed; low = envolve inferred/external).
    """
    run = get_run_or_404(session, run_id)
    graph = build_graph(session, run.id or 0)
    result = detect_cycles(
        graph, max_cycles=max_cycles, max_cycle_size=max_cycle_size
    )
    result["run_id"] = run.id
    result["project_id"] = run.project_id
    return result
