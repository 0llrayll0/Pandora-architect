"""Arquiteto IA (Fase 6): relatório arquitetural da run.

Combina o determinístico com o opcional:

1. heurísticas puras (``analysis/heuristics.py``) → ``findings`` estruturados;
2. narrativa via Ollama local (``/api/generate``) → resumo, fortes, riscos e
   plano de ação em JSON.

Ollama é **opcional**: timeout, erro de conexão ou resposta inválida caem no
modo heurística (``ollama_used: false``) — o endpoint nunca retorna 500 por
causa do LLM. Relatório cacheado por run (tabela ``architecture_reports``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..analysis.graph import build_graph, graph_payload
from ..analysis.heuristics import SEVERITY_ORDER, build_findings
from ..analysis.metrics import ensure_run_metrics
from ..config import get_settings
from ..db import get_engine, get_session
from ..errors import bad_request, not_found
from ..models import ArchitectureReport, RunState
from .common import get_run_or_404

router = APIRouter(prefix="/ai", tags=["ai"])

#: Timeout máximo da chamada ao Ollama (connect + read).
OLLAMA_TIMEOUT = 60.0
#: Máximo de ações no plano (contrato do prompt).
MAX_ACTIONS = 5
#: Nós por grau enviados ao LLM.
TOP_NODES_FOR_PROMPT = 20
#: Ciclos enviados ao LLM (assinaturas compactas).
CYCLES_FOR_PROMPT = 10
#: Máximo de itens em listas do relatório persistido (o LLM pode encher a lista).
MAX_LIST_ITEMS = 20
#: Tamanho máximo de cada texto livre persistido (resumo, descrições, ações).
MAX_TEXT_CHARS = 2000

SEVERITY_IMPACT = {"high": "Alto", "medium": "Médio", "low": "Baixo"}

SYSTEM_PROMPT = (
    "Você é um arquiteto de software sênior. Recebe um JSON com findings de "
    "heurísticas determinísticas sobre um repositório (grafo de imports). "
    "Analise SOMENTE o que foi fornecido — nada de dados inventados, sem "
    "código, sem mensagens fora do JSON. Responda em JSON válido, sem "
    "markdown e sem comentários, exatamente com esta forma: "
    '{"executive_summary": "2-3 frases", "strengths": ["..."], '
    '"risks": [{"title": "...", "severity": "high|medium|low", '
    '"description": "..."}], "action_plan": [{"action": "...", '
    '"justification": "...", "impact": "..."}]}'
)

USER_PROMPT_HEADER = (
    "Analise os findings e gere: 1) Resumo executivo (2-3 frases), "
    "2) Pontos fortes (lista), 3) Riscos (lista priorizada por severidade), "
    "4) Plano de ação (passos concretos, máxima 5 ações, cada uma com: "
    "ação, justificativa, impacto estimado). Responda em JSON válido.\n\n"
    "Dados da análise:\n"
)


# ---------------------------------------------------------------------------
# Heurística → narrativa de fallback (sem LLM)
# ---------------------------------------------------------------------------


def _derive_strengths(metrics: dict[str, Any], findings: list[dict[str, Any]]) -> list[str]:
    """Pontos fortes derivados dos números reais (nada inventado)."""
    totals = metrics.get("totals") or {}
    cycles = metrics.get("cycles") or {}
    strengths: list[str] = []

    if cycles.get("available") and int(cycles.get("count") or 0) == 0:
        strengths.append("Sem ciclos de import entre arquivos (grafo acíclico entre arquivos).")

    density = float(totals.get("density") or 0.0)
    nodes = int(totals.get("nodes") or 0)
    if nodes and 0 < density <= 0.05:
        strengths.append(
            f"Densidade de acoplamento baixa ({density:g}) — poucas arestas "
            "em relação ao total possível."
        )

    largest_scc = int(totals.get("largest_scc") or 0)
    if nodes and largest_scc <= 1:
        strengths.append(
            f"Sem agrupamentos fortemente conectados (maior SCC = {largest_scc})."
        )

    if not findings:
        strengths.append("Nenhum achado estrutural crítico nas heurísticas aplicadas.")

    if not strengths:
        strengths.append(
            "Estrutura pequena e suficientemente explícita para navegação "
            "(nenhuma métrica de acoplamento fora dos limites críticos)."
        )
    return strengths[:5]


def _risks_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Findings viram a lista priorizada de riscos (severidade → impacto)."""
    ordered = sorted(
        findings, key=lambda f: (SEVERITY_ORDER.get(f.get("severity", ""), 9), f.get("type", ""))
    )
    return [
        {
            "title": str(f.get("title") or f.get("type") or "Achado"),
            "severity": str(f.get("severity") or "low"),
            "description": str(f.get("description") or ""),
        }
        for f in ordered
    ]


def _action_plan_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for finding in findings:
        if len(plan) >= MAX_ACTIONS:
            break
        plan.append(
            {
                "action": str(finding.get("action") or ""),
                "justification": str(finding.get("description") or ""),
                "impact": SEVERITY_IMPACT.get(str(finding.get("severity")), "Baixo"),
            }
        )
    if not plan:
        plan.append(
            {
                "action": "Manter a cobertura de métricas por run como linha de base",
                "justification": "Nenhum achado estrutural foi detectado; monitore "
                "regressões comparando runs consecutivas do mesmo projeto.",
                "impact": "Baixo",
            }
        )
    return plan


def _heuristic_report(
    findings: list[dict[str, Any]],
    metrics: dict[str, Any],
    graph_totals: dict[str, Any],
    run_id: int,
) -> dict[str, Any]:
    """Relatório completo sem LLM (sempre disponível, nunca 500)."""
    cycles = metrics.get("cycles") or {}
    cycle_count = int(cycles.get("count") or 0)
    high = sum(1 for f in findings if f.get("severity") == "high")

    sentences = [
        f"Análise arquitetural da run #{run_id} sobre "
        f"{int(graph_totals.get('nodes') or 0)} nós e "
        f"{int(graph_totals.get('edges') or 0)} arestas "
        f"(densidade {float(graph_totals.get('density') or 0):g})."
    ]
    if findings:
        sentences.append(
            f"Foram identificados {len(findings)} achado(s) estrutural(is), "
            f"sendo {high} de severidade alta."
        )
    else:
        sentences.append("Nenhum achado estrutural relevante foi detectado pelas heurísticas.")
    if cycles.get("available") and cycle_count > 0:
        sentences.append(
            f"O grafo contém {cycle_count} ciclo(s) de import entre arquivos "
            "(dependência circular) que merecem atenção prioritária."
        )

    return {
        "executive_summary": " ".join(sentences),
        "strengths": _derive_strengths(metrics, findings),
        "risks": _risks_from_findings(findings),
        "action_plan": _action_plan_from_findings(findings),
    }


# ---------------------------------------------------------------------------
# Ollama (opcional)
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any] | None:
    """JSON puro, JSON dentro de ```` ```json``` ```` ou o primeiro objeto.

    Cobre: JSON puro, fence ```` ```json``` ```` (com ou sem espaço antes do
    tipo), fence sem tipo, dois objetos no mesmo texto (usa o primeiro) e
    texto sem JSON (``None``).
    """
    if not isinstance(text, str) or not text.strip():
        return None

    def _try(candidate: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    direct = _try(text.strip())
    if direct is not None:
        return direct

    if "```" in text:
        for chunk in text.split("```")[1:]:
            cleaned = chunk.strip()
            if cleaned[:4].lower() == "json":
                cleaned = cleaned[4:].strip()
            parsed = _try(cleaned)
            if parsed is not None:
                return parsed

    # primeiro objeto completo: raw_decode ignora o que vem depois do fecho
    decoder = json.JSONDecoder()
    stripped = text.strip()
    index = stripped.find("{")
    while index != -1:
        try:
            parsed, _end = decoder.raw_decode(stripped[index:])
        except ValueError:
            index = stripped.find("{", index + 1)
            continue
        if isinstance(parsed, dict):
            return parsed
        index = stripped.find("{", index + 1)
    return None


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _coerce_report(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza a resposta do LLM; ``None`` quando inutilizável."""
    summary = raw.get("executive_summary")
    if not isinstance(summary, str) or not summary.strip():
        return None

    risks: list[dict[str, str]] = []
    if isinstance(raw.get("risks"), list):
        for item in raw["risks"]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "low").lower()
            if severity not in SEVERITY_ORDER:
                severity = "low"
            risks.append(
                {
                    "title": str(item.get("title") or "Risco"),
                    "severity": severity,
                    "description": str(item.get("description") or ""),
                }
            )

    action_plan: list[dict[str, str]] = []
    if isinstance(raw.get("action_plan"), list):
        for item in raw["action_plan"][:MAX_ACTIONS]:
            if not isinstance(item, dict):
                continue
            action_plan.append(
                {
                    "action": str(item.get("action") or ""),
                    "justification": str(item.get("justification") or ""),
                    "impact": str(item.get("impact") or ""),
                }
            )

    return {
        "executive_summary": summary.strip(),
        "strengths": _as_str_list(raw.get("strengths")),
        "risks": risks,
        "action_plan": action_plan,
    }


def _clip(text: str) -> str:
    """Trunca texto livre antes de persistir (defesa contra respostas gigantes)."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS]


def _sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Aplica limites de tamanho antes de persistir (LLM ou heurística).

    - ``risks`` e ``strengths``: no máximo ``MAX_LIST_ITEMS`` itens;
    - textos livres (resumo, títulos, descrições, ações): ``MAX_TEXT_CHARS``.
    """
    risks = report.get("risks") if isinstance(report.get("risks"), list) else []
    strengths = report.get("strengths") if isinstance(report.get("strengths"), list) else []
    plan = report.get("action_plan") if isinstance(report.get("action_plan"), list) else []

    return {
        "executive_summary": _clip(str(report.get("executive_summary") or "")),
        "strengths": [_clip(str(item)) for item in strengths[:MAX_LIST_ITEMS]],
        "risks": [
            {
                "title": _clip(str(item.get("title") or "")),
                "severity": str(item.get("severity") or "low"),
                "description": _clip(str(item.get("description") or "")),
            }
            for item in risks[:MAX_LIST_ITEMS]
            if isinstance(item, dict)
        ],
        "action_plan": [
            {
                "action": _clip(str(item.get("action") or "")),
                "justification": _clip(str(item.get("justification") or "")),
                "impact": _clip(str(item.get("impact") or "")),
            }
            for item in plan[:MAX_ACTIONS]
            if isinstance(item, dict)
        ],
    }


def _call_ollama(prompt: str, *, url: str, model: str) -> dict[str, Any] | None:
    """POST ``/api/generate`` com timeout de 60s. ``None`` em qualquer falha."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - dependência de dev ausente
        return None

    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
            response = client.post(
                f"{url.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                },
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None

    if not isinstance(body, dict):
        return None
    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        return None
    return _coerce_report(_extract_json(text) or {})


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def _graph_totals(payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Totais do grafo como ``Record<string, number>`` (só escalares)."""
    totals: dict[str, Any] = {}

    def _keep(source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            totals[key] = value

    _keep(metrics.get("totals") or {})
    _keep(payload.get("counts") or {})
    return totals


def _prompt_for_llm(
    findings: list[dict[str, Any]],
    metrics: dict[str, Any],
    graph_totals: dict[str, Any],
    run_id: int,
) -> str:
    """Input compacto: findings + top 20 nós por grau + ciclos + totais."""
    degrees = (metrics.get("degrees") or {}).get("top_total") or []
    top_nodes = [
        {
            "label": row.get("label", ""),
            "type": row.get("type", ""),
            "degree": row.get("degree", 0),
            "in_degree": row.get("in_degree", 0),
            "out_degree": row.get("out_degree", 0),
        }
        for row in degrees[:TOP_NODES_FOR_PROMPT]
        if isinstance(row, dict)
    ]
    cycles = metrics.get("cycles") or {}
    data = {
        "run_id": run_id,
        "totals": graph_totals,
        "top_nodes_by_degree": top_nodes,
        "cycles": {
            "available": bool(cycles.get("available")),
            "count": int(cycles.get("count") or 0),
            "signatures": [
                [node.split(":", 1)[-1] for node in cycle]
                for cycle in (cycles.get("signatures") or [])[:CYCLES_FOR_PROMPT]
            ],
        },
        "findings": [
            {
                "type": f.get("type"),
                "severity": f.get("severity"),
                "title": f.get("title"),
                "description": f.get("description"),
                "action": f.get("action"),
            }
            for f in findings
        ],
    }
    return USER_PROMPT_HEADER + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _persist(
    session: Session,
    run_id: int,
    project_id: int,
    payload: dict[str, Any],
    *,
    ollama_used: bool,
    ollama_model: str,
) -> None:
    """Upsert idempotente por ``run_id`` (regenerar sobrescreve a linha).

    Dois POSTs simultâneos para a mesma run podem colidir no ``INSERT``
    (``run_id`` é único): o ``IntegrityError`` é capturado e a operação é
    refazida como ``UPDATE`` — nunca duplica linha nem estoura 500.
    """
    row = session.exec(
        select(ArchitectureReport).where(ArchitectureReport.run_id == run_id)
    ).first()
    if row is None:
        row = ArchitectureReport(run_id=run_id, project_id=project_id)
    row.project_id = project_id
    row.payload = payload
    row.ollama_used = ollama_used
    row.ollama_model = ollama_model
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Corrida: outra transação inseriu a linha — refaz como update.
        session.rollback()
        existing = session.exec(
            select(ArchitectureReport).where(ArchitectureReport.run_id == run_id)
        ).first()
        if existing is None:  # pragma: no cover - perda real do banco
            raise
        existing.project_id = project_id
        existing.payload = payload
        existing.ollama_used = ollama_used
        existing.ollama_model = ollama_model
        session.add(existing)
        session.commit()
        row = existing
    session.refresh(row)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/report")
def generate_report(run_id: int) -> dict[str, Any]:
    """Gera (e cacheia) o relatório arquitetural da run.

    Heurísticas sempre rodam; Ollama é tentado e pode falhar silenciosamente
    (``ollama_used: false``) — a resposta continua 200 com heurísticas puras.

    Apenas runs ``completed`` são aceitas (400 ``run_not_active``). A sessão
    do SQLAlchemy fica aberta só na leitura curta e na persistência final:
    a chamada ao LLM (timeout de 60s) roda com o pool livre.
    """
    with Session(get_engine()) as session:
        run = get_run_or_404(session, run_id)
        if run.state != RunState.COMPLETED.value:
            raise bad_request(
                f"A análise {run_id} ainda não foi concluída (estado: {run.state}) — "
                "gere o relatório apenas após a análise terminar.",
                code="run_not_active",
            )
        project_id = run.project_id
        metrics = ensure_run_metrics(session, run_id, project_id)
        graph = build_graph(session, run_id)

    # --- sessão fechada: heurísticas + LLM (até 60s sem segurar conexão) ---
    payload = graph_payload(graph)
    graph_totals = _graph_totals(payload, metrics)
    findings = build_findings(graph, metrics)

    settings = get_settings()
    llm = _call_ollama(
        _prompt_for_llm(findings, metrics, graph_totals, run_id),
        url=settings.ollama_url,
        model=settings.ollama_model,
    )

    if llm is not None:
        report = {
            "executive_summary": llm["executive_summary"],
            "strengths": llm["strengths"],
            "risks": llm["risks"],
            "action_plan": llm["action_plan"] or _action_plan_from_findings(findings),
        }
        ollama_used = True
        ollama_model = settings.ollama_model
    else:
        report = _heuristic_report(findings, metrics, graph_totals, run_id)
        ollama_used = False
        ollama_model = ""

    report = _sanitize_report(report)

    body = {
        "run_id": run_id,
        "project_id": project_id,
        "ollama_used": ollama_used,
        "ollama_model": ollama_model or None,
        "executive_summary": report["executive_summary"],
        "strengths": report["strengths"],
        "risks": report["risks"],
        "action_plan": report["action_plan"],
        "findings": findings,
        "graph_totals": graph_totals,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    with Session(get_engine()) as session:
        _persist(
            session, run_id, project_id, body, ollama_used=ollama_used, ollama_model=ollama_model
        )
    return body


@router.get("/runs/{run_id}/report")
def get_report(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Relatório cacheado da run; 404 ``report_not_found`` se ainda não gerado."""
    get_run_or_404(session, run_id)
    row = session.exec(
        select(ArchitectureReport).where(ArchitectureReport.run_id == run_id)
    ).first()
    if row is None or not row.payload:
        raise not_found(
            f"Relatório da análise {run_id} ainda não foi gerado — "
            f"gere com POST /api/ai/runs/{run_id}/report.",
            code="report_not_found",
        )
    return row.payload
