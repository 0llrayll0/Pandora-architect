"""Arquiteto IA (Fase 6): relatório arquitetural da run.

Combina o determinístico com o opcional:

1. heurísticas puras (``analysis/heuristics.py``) → ``findings`` estruturados
   e a seção ``dependencies`` (interna/externa + recomendações);
2. narrativa via LLM → resumo, fortes, riscos e plano de ação em JSON
   (recomendações de dependências do LLM são somadas às heurísticas).

O provedor é configurável (``GET/PUT /api/ai/config``): Ollama local
(``/api/generate``), API compatível com OpenAI ou endpoint customizado
(``/chat/completions``), Anthropic Claude (``/v1/messages``) e Google Gemini
(``:generateContent``). A chave de API fica só no backend: nunca é
devolvida em GET nem logada.

O LLM é **opcional**: timeout, erro de conexão, resposta inválida ou chave
ausente caem no modo heurística (``ollama_used: false``) — o endpoint nunca
retorna 500 por causa do LLM. Relatório cacheado por run (tabela
``architecture_reports``).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..analysis.graph import build_graph, graph_payload
from ..analysis.heuristics import SEVERITY_ORDER, build_findings
from ..analysis.metrics import ensure_run_metrics
from ..config import AI_PROVIDERS, get_settings
from ..db import get_engine, get_session
from ..errors import bad_request, not_found
from ..models import AppSetting, ArchitectureReport, Dependency, DependencyClass, RunState, utcnow
from .common import get_run_or_404

router = APIRouter(prefix="/ai", tags=["ai"])

#: Timeout máximo da chamada ao LLM (connect + read) — vale para todos os
#: provedores (Ollama, OpenAI-compatible, custom, Anthropic e Gemini).
LLM_TIMEOUT = 60.0
#: Provedores aceitos pelo campo ``provider`` — vem de ``config.AI_PROVIDERS``
#: (fonte única: ollama, openai, custom, anthropic, gemini).
#: Chaves de configuração persistidas na tabela ``settings``.
AI_SETTING_KEYS = ("ai_provider", "ai_base_url", "ai_model", "ai_api_key")
#: Base URL padrão quando o provedor é OpenAI e ``ai_base_url`` está vazio.
OPENAI_BASE_URL = "https://api.openai.com/v1"
#: Base URL/modelo padrão do provedor Anthropic (Claude).
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
#: Base URL/modelo padrão do provedor Google Gemini.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-2.0-flash"

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
#: Dependências (interna/externa) resumidas enviadas ao LLM.
DEPS_FOR_PROMPT = 15
#: Recomendações heurísticas por tipo (hub / uso único) mantidas na lista final
#: — evita que a lista estrague por mensagens repetitivas antes dos agregados.
RECOMMENDATIONS_PER_KIND = 5
#: Limite de pacotes de terceiros que dispara o alerta de manutenção.
THIRD_PARTY_ALERT_THRESHOLD = 20

#: Lista explícita dos módulos da stdlib mais comuns (inclusive alguns
#: removidos do interpretador, como ``asyncore``/``telnetlib``).
_EXPLICIT_STDLIB_TEXT = """
    os sys math time dataclasses collections typing pathlib json re subprocess
    threading logging abc enum functools itertools hashlib argparse shlex signal
    platform socket struct io copy datetime warnings traceback textwrap uuid csv
    glob shutil tempfile unicodedata string random statistics array bisect heapq
    weakref types inspect dis ast tokenize keyword token symbol builtins
    __future__ site gc atexit code codeop readline rlcompleter importlib pkgutil
    modulefinder runpy pydoc doctest unittest test lib2to3 ensurepip venv zipapp
    zipfile tarfile gzip bz2 lzma zlib configparser netrc xdrlib plistlib
    socketserver http urllib ftplib poplib imaplib nntplib smtplib smtpd
    telnetlib ssl select selectors asyncore asynchat asyncio concurrent
    multiprocessing queue sched contextvars contextlib __main__
    """
#: Módulos da stdlib usados em ``is_stdlib``: lista canônica do interpretador
#: (``sys.stdlib_module_names``) unida à lista explícita acima.
STDLIB_MODULES: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", ())
) | frozenset(_EXPLICIT_STDLIB_TEXT.split())

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
    '"justification": "...", "impact": "..."}], '
    '"dependencies": {"recommendations": ["..."]}}'
)

USER_PROMPT_HEADER = (
    "Analise os findings e gere: 1) Resumo executivo (2-3 frases), "
    "2) Pontos fortes (lista), 3) Riscos (lista priorizada por severidade), "
    "4) Plano de ação (passos concretos, máxima 5 ações, cada uma com: "
    "ação, justificativa, impacto estimado), 5) recommendations de "
    "dependências (lista de strings comentando as dependências internas e "
    "externas fornecidas). Responda em JSON válido.\n\n"
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
# Dependências (seção do relatório)
# ---------------------------------------------------------------------------


def _is_stdlib(module: str) -> bool:
    """``True`` quando o top-level do módulo pertence à stdlib."""
    top = module.split(".")[0] if module else ""
    return bool(top) and top in STDLIB_MODULES


def _dependencies_section(rows: list[Any]) -> dict[str, Any]:
    """Agrega as linhas da tabela ``dependencies`` da run.

    - ``internal``: alvos ``confirmed`` agrupados por módulo (``imported_by``
      deduplica ``source_path`` e ``out_degree`` = quantos arquivos importam);
    - ``external``: pacotes ``external`` agrupados pelo top-level
      (``import_count`` = arquivos distintos que o importam, ``is_stdlib`` =
      stdlib) — terceiros vêm primeiro porque é o que a UI exibe;
    - ``recommendations``: heurísticas sobre os dados agregados.
    """
    internal: dict[str, dict[str, Any]] = {}
    external: dict[str, dict[str, Any]] = {}
    external_sources: dict[str, set[str]] = {}

    for row in rows:
        source_path = str(getattr(row, "source_path", "") or "")
        classification = str(getattr(row, "classification", "") or "")
        module = str(getattr(row, "module", "") or "")

        if classification == DependencyClass.CONFIRMED.value:
            name = str(getattr(row, "target_module", "") or "") or module
            if not name:
                continue
            entry = internal.get(name)
            if entry is None:
                entry = internal[name] = {"name": name, "imported_by": [], "out_degree": 0}
            if source_path and source_path not in entry["imported_by"]:
                entry["imported_by"].append(source_path)
                entry["out_degree"] += 1
        elif classification == DependencyClass.EXTERNAL.value:
            name = module.split(".")[0] if module else ""
            if not name:
                continue
            entry = external.get(name)
            if entry is None:
                entry = external[name] = {
                    "name": name,
                    "import_count": 0,
                    "is_stdlib": _is_stdlib(name),
                }
                external_sources[name] = set()
            if source_path and source_path not in external_sources[name]:
                external_sources[name].add(source_path)
                entry["import_count"] += 1

    internal_list = sorted(internal.values(), key=lambda e: (-e["out_degree"], e["name"]))
    # terceiros (is_stdlib False) antes da stdlib; dentro do grupo, por uso
    external_list = sorted(
        external.values(), key=lambda e: (bool(e["is_stdlib"]), -e["import_count"], e["name"])
    )
    return {
        "internal": internal_list,
        "external": external_list,
        "recommendations": _dependency_recommendations(internal_list, external_list),
    }


def _dependency_recommendations(
    internal: list[dict[str, Any]], external: list[dict[str, Any]]
) -> list[str]:
    """Recomendações heurísticas derivadas dos dados agregados (nada inventado)."""
    recommendations: list[str] = []

    hubs = [e for e in internal if _as_int(e.get("out_degree")) > 5]
    for entry in hubs[:RECOMMENDATIONS_PER_KIND]:
        recommendations.append(
            f"O módulo {entry['name']} é um hub central (importado por "
            f"{entry['out_degree']} módulos) — considere estabilizar sua API pública"
        )

    third_party = [e for e in external if not e.get("is_stdlib")]
    single_use = [e for e in third_party if _as_int(e.get("import_count")) == 1]
    for entry in single_use[:RECOMMENDATIONS_PER_KIND]:
        recommendations.append(
            f"O pacote {entry['name']} é usado apenas em 1 arquivo — avalie se a "
            "dependência justifica o custo de manutenção"
        )

    if len(third_party) > THIRD_PARTY_ALERT_THRESHOLD:
        recommendations.append(
            f"O projeto tem {len(third_party)} dependências externas — mantenha um "
            "requirements.txt/pyproject.toml atualizado e rode auditoria de segurança "
            "regularmente"
        )

    names = {str(e.get("name") or "") for e in third_party}
    if "cv2" in names or "numpy" in names:
        recommendations.append(
            "Dependências de processamento de imagem (opencv/numpy) detectadas — "
            "garanta que estão no requirements.txt"
        )
    return recommendations


def _merge_dependencies(base: dict[str, Any], llm: Any) -> dict[str, Any]:
    """Seção das heurísticas + narrativa do LLM (deduplicada, ordem estável).

    As listas vêm sempre do banco (dado real); o LLM só acrescenta
    ``recommendations``. Sem linhas na run, cai nas listas do modelo.
    """
    llm_deps = llm if isinstance(llm, dict) else {}
    internal = base.get("internal") or llm_deps.get("internal") or []
    external = base.get("external") or llm_deps.get("external") or []

    recommendations: list[str] = []
    for item in _as_str_list(llm_deps.get("recommendations")) + list(
        base.get("recommendations") or []
    ):
        if item not in recommendations:
            recommendations.append(item)
    return {"internal": internal, "external": external, "recommendations": recommendations}


# ---------------------------------------------------------------------------
# Resposta do LLM → relatório
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


def _as_int(value: Any, default: int = 0) -> int:
    """Inteiro não-negativo a partir de qualquer coisa (contagens do LLM)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim"}
    if value is None:
        return default
    return bool(value)


def _coerce_dependencies(raw: Any) -> dict[str, Any] | None:
    """Normaliza a seção ``dependencies`` devolvida pelo LLM (``None`` se ausente).

    Cada item é validado individualmente: entradas malformadas são descartadas,
    textos truncados em ``MAX_TEXT_CHARS`` e listas em ``MAX_LIST_ITEMS``.
    """
    if not isinstance(raw, dict):
        return None

    internal: list[dict[str, Any]] = []
    if isinstance(raw.get("internal"), list):
        for item in raw["internal"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            imported = item.get("imported_by")
            imported_by = (
                [_clip(str(path)) for path in imported if str(path).strip()]
                if isinstance(imported, list)
                else []
            )
            internal.append(
                {
                    "name": _clip(name),
                    "imported_by": imported_by[:MAX_LIST_ITEMS],
                    "out_degree": _as_int(item.get("out_degree"), len(imported_by)),
                }
            )

    external: list[dict[str, Any]] = []
    if isinstance(raw.get("external"), list):
        for item in raw["external"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            flag = item.get("is_stdlib")
            external.append(
                {
                    "name": _clip(name),
                    "import_count": _as_int(item.get("import_count")),
                    "is_stdlib": _is_stdlib(name) if flag is None else _as_bool(flag),
                }
            )

    return {
        "internal": internal,
        "external": external,
        "recommendations": _as_str_list(raw.get("recommendations")),
    }


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
        "dependencies": _coerce_dependencies(raw.get("dependencies")),
    }


def _clip(text: str) -> str:
    """Trunca texto livre antes de persistir (defesa contra respostas gigantes)."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS]


def _sanitize_dependencies(deps: Any) -> dict[str, Any]:
    """Limita a seção ``dependencies`` (``None``/lixo vira estrutura vazia)."""
    if not isinstance(deps, dict):
        deps = {}
    internal = deps.get("internal") if isinstance(deps.get("internal"), list) else []
    external = deps.get("external") if isinstance(deps.get("external"), list) else []
    recommendations = (
        deps.get("recommendations") if isinstance(deps.get("recommendations"), list) else []
    )

    sanitized_internal: list[dict[str, Any]] = []
    for item in internal[:MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        name = _clip(str(item.get("name") or ""))
        imported = item.get("imported_by")
        imported_by = (
            [_clip(str(path)) for path in imported if str(path).strip()]
            if isinstance(imported, list)
            else []
        )
        sanitized_internal.append(
            {
                "name": name,
                "imported_by": imported_by[:MAX_LIST_ITEMS],
                "out_degree": _as_int(item.get("out_degree"), len(imported_by)),
            }
        )

    sanitized_external: list[dict[str, Any]] = []
    for item in external[:MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        name = _clip(str(item.get("name") or ""))
        flag = item.get("is_stdlib")
        sanitized_external.append(
            {
                "name": name,
                "import_count": _as_int(item.get("import_count")),
                "is_stdlib": _is_stdlib(name) if flag is None else _as_bool(flag),
            }
        )

    return {
        "internal": sanitized_internal,
        "external": sanitized_external,
        "recommendations": [
            _clip(str(item)) for item in recommendations[:MAX_LIST_ITEMS] if str(item).strip()
        ],
    }


def _sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Aplica limites de tamanho antes de persistir (LLM ou heurística).

    - ``risks``, ``strengths`` e as listas de ``dependencies``: no máximo
      ``MAX_LIST_ITEMS`` itens;
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
        "dependencies": _sanitize_dependencies(report.get("dependencies")),
    }


# ---------------------------------------------------------------------------
# Provedor de IA (configurável) + chamada ao LLM
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AiConfig:
    """Configuração efetiva do provedor (DB > env > padrões).

    ``api_key`` serve só para montar o header ``Authorization`` — nunca é
    serializada numa resposta de API.
    """

    provider: str
    base_url: str
    model: str
    api_key: str


def _load_ai_overrides() -> dict[str, Any]:
    """Overrides persistidos na tabela ``settings`` (prioridade sobre env)."""
    try:
        with Session(get_engine()) as session:
            rows = session.exec(select(AppSetting).where(AppSetting.key.in_(AI_SETTING_KEYS))).all()
            return {str(row.key): row.value for row in rows if row.value is not None}
    except Exception:  # pragma: no cover - override é opcional
        return {}


def _resolve_ai_config() -> AiConfig:
    """Junta DB + env + defaults em uma única configuração de provedor."""
    settings = get_settings()
    over = _load_ai_overrides()

    provider = str(over.get("ai_provider") or settings.ai_provider or "ollama")
    provider = provider.strip().lower()
    if provider not in AI_PROVIDERS:
        provider = "ollama"

    api_key = str(over.get("ai_api_key") or settings.ai_api_key or "").strip()
    base_url = str(over.get("ai_base_url") or settings.ai_base_url or "").strip()
    model = str(over.get("ai_model") or settings.ai_model or "").strip()

    if not base_url:
        if provider == "ollama":
            base_url = settings.ollama_url
        elif provider == "openai":
            base_url = OPENAI_BASE_URL
        elif provider == "anthropic":
            base_url = ANTHROPIC_BASE_URL
        elif provider == "gemini":
            base_url = GEMINI_BASE_URL
    if not model:
        if provider == "anthropic":
            model = ANTHROPIC_MODEL
        elif provider == "gemini":
            model = GEMINI_MODEL
        else:
            model = settings.ollama_model

    return AiConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
    )


def _call_llm(prompt: str, config: AiConfig) -> dict[str, Any] | None:
    """Roteia para o provedor configurado. ``None`` em qualquer falha.

    Nunca 500: provedores que exigem chave (openai/custom/anthropic/gemini)
    sem ``api_key`` caem direto em ``None`` (o chamador segue com as
    heurísticas).
    """
    if config.provider == "ollama":
        return _call_ollama(prompt, config)
    if not config.api_key:
        return None
    if config.provider == "anthropic":
        return _call_anthropic(prompt, config)
    if config.provider == "gemini":
        return _call_gemini(prompt, config)
    return _call_openai(prompt, config)


def _call_ollama(prompt: str, config: AiConfig) -> dict[str, Any] | None:
    """POST ``{base}/api/generate`` com timeout de 60s. ``None`` em falha."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - dependência de dev ausente
        return None

    if not config.base_url:
        return None

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(
                f"{config.base_url}/api/generate",
                json={
                    "model": config.model,
                    "prompt": prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                },
            )
            response.raise_for_status()
            body = response.json()
    except Exception:  # qualquer falha do LLM vira heurística (nunca 500)
        return None

    if not isinstance(body, dict):
        return None
    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        return None
    return _coerce_report(_extract_json(text) or {})


def _call_openai(prompt: str, config: AiConfig) -> dict[str, Any] | None:
    """POST ``{base}/chat/completions`` (OpenAI-compatible). ``None`` em falha."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - dependência de dev ausente
        return None

    if not config.base_url:
        return None

    headers = {"Content-Type": "application/json"}
    if config.api_key:  # sem chave não chegamos aqui (_call_llm já barrava)
        headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            body = response.json()
    except Exception:  # qualquer falha do LLM vira heurística (nunca 500)
        return None

    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        return None
    return _coerce_report(_extract_json(text) or {})


def _call_anthropic(prompt: str, config: AiConfig) -> dict[str, Any] | None:
    """POST ``{base}/v1/messages`` (Anthropic Messages API).

    ``system`` vai separado do prompt do usuário (user message). ``None`` em
    qualquer falha (nunca 500); sem ``api_key`` também ``None``.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - dependência de dev ausente
        return None

    if not config.api_key or not config.base_url:
        return None

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(
                f"{config.base_url}/v1/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config.model,
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            body = response.json()
    except Exception:  # qualquer falha do LLM vira heurística (nunca 500)
        return None

    if not isinstance(body, dict):
        return None
    content = body.get("content")
    if not isinstance(content, list):
        return None
    # lista de blocos: usa o primeiro com type == "text" (ignora thinking etc.)
    text = next(
        (
            block.get("text")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ),
        None,
    )
    if not isinstance(text, str) or not text.strip():
        return None
    return _coerce_report(_extract_json(text) or {})


def _call_gemini(prompt: str, config: AiConfig) -> dict[str, Any] | None:
    """POST ``{base}/models/{model}:generateContent`` (Google Gemini).

    A chave vai na query string (``?key=``) e o SYSTEM_PROMPT vira
    ``systemInstruction`` — o prompt do usuário fica em ``contents``. ``None``
    em qualquer falha (nunca 500); sem ``api_key`` também ``None``.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - dependência de dev ausente
        return None

    if not config.api_key or not config.base_url:
        return None

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            response = client.post(
                f"{config.base_url}/models/{config.model}:generateContent"
                f"?key={config.api_key}",
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json",
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
    except Exception:  # qualquer falha do LLM vira heurística (nunca 500)
        return None

    if not isinstance(body, dict):
        return None
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    first = candidates[0]
    if not isinstance(first, dict) or not isinstance(first.get("content"), dict):
        return None
    parts = first["content"].get("parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
        return None
    text = parts[0].get("text")
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
    dependencies: dict[str, Any] | None = None,
) -> str:
    """Input compacto: findings + top 20 nós por grau + ciclos + dependências."""
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
        "dependencies": _deps_for_prompt(dependencies),
    }
    return USER_PROMPT_HEADER + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _deps_for_prompt(dependencies: dict[str, Any] | None) -> dict[str, list[Any]]:
    """Resumo das dependências para o LLM (só escalares, limitado)."""
    if not isinstance(dependencies, dict):
        return {"internal": [], "external": []}

    internal = [
        {"name": item.get("name"), "out_degree": _as_int(item.get("out_degree"))}
        for item in (dependencies.get("internal") or [])[:DEPS_FOR_PROMPT]
        if isinstance(item, dict)
    ]
    external = [
        {
            "name": item.get("name"),
            "import_count": _as_int(item.get("import_count")),
            "is_stdlib": bool(item.get("is_stdlib")),
        }
        for item in (dependencies.get("external") or [])
        if isinstance(item, dict) and not item.get("is_stdlib")
    ][:DEPS_FOR_PROMPT]
    return {"internal": internal, "external": external}


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

    Heurísticas sempre rodam; o LLM (provedor configurado) é tentado e pode
    falhar silenciosamente (``ollama_used: false``) — a resposta continua
    200 com heurísticas puras.

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
        dependency_rows = session.exec(
            select(Dependency).where(Dependency.run_id == run_id)
        ).all()

    # --- sessão fechada: heurísticas + LLM (até 60s sem segurar conexão) ---
    payload = graph_payload(graph)
    graph_totals = _graph_totals(payload, metrics)
    findings = build_findings(graph, metrics)
    dependencies = _dependencies_section(list(dependency_rows))

    ai_config = _resolve_ai_config()
    llm = _call_llm(
        _prompt_for_llm(findings, metrics, graph_totals, run_id, dependencies=dependencies),
        ai_config,
    )

    if llm is not None:
        report = {
            "executive_summary": llm["executive_summary"],
            "strengths": llm["strengths"],
            "risks": llm["risks"],
            "action_plan": llm["action_plan"] or _action_plan_from_findings(findings),
        }
        ollama_used = True
        ollama_model = ai_config.model
    else:
        report = _heuristic_report(findings, metrics, graph_totals, run_id)
        ollama_used = False
        ollama_model = ""

    # Dependências SEMPRE vêm do banco (heurística), com o LLM só acrescentando
    # recomendações — o relatório nunca fica sem a seção.
    report["dependencies"] = _merge_dependencies(
        dependencies, llm.get("dependencies") if llm else None
    )
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
        "dependencies": report["dependencies"],
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


# ---------------------------------------------------------------------------
# Configuração do provedor de IA (GET/PUT /api/ai/config)
# ---------------------------------------------------------------------------


class AiConfigUpdate(BaseModel):
    """Payload do PUT /api/ai/config.

    ``api_key``: ``None`` ou string vazia mantém a chave já gravada (nunca
    apaga); string não-vazia substitui. A chave nunca sai do backend.
    """

    provider: str = "ollama"
    base_url: str = ""
    model: str = ""
    api_key: str | None = None


@router.get("/config")
def get_ai_config() -> dict[str, Any]:
    """Configuração atual do provedor de IA.

    Endpoint público e somente leitura: expõe provider/base_url/model e um
    booleano ``has_api_key`` — a chave em si NUNCA é devolvida (nem parcial).
    """
    cfg = _resolve_ai_config()
    return {
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_api_key": bool(cfg.api_key),
    }


@router.put("/config")
def update_ai_config(payload: AiConfigUpdate) -> dict[str, Any]:
    """Persiste a configuração do provedor na tabela ``settings``.

    Os valores gravados aqui têm prioridade sobre as variáveis de ambiente
    (DB > env). ``api_key`` só é atualizada quando enviada não-vazia —
    ``null``/vazia preserva a chave existente.
    """
    provider = payload.provider.strip().lower()
    if provider not in AI_PROVIDERS:
        raise bad_request(
            f"Provedor inválido: {payload.provider!r} (use: {', '.join(AI_PROVIDERS)}).",
            code="invalid_provider",
        )

    new_api_key = (payload.api_key or "").strip()
    values = {
        "ai_provider": provider,
        "ai_base_url": payload.base_url.strip(),
        "ai_model": payload.model.strip(),
    }
    if new_api_key:
        values["ai_api_key"] = new_api_key

    with Session(get_engine()) as session:
        rows = {
            str(row.key): row
            for row in session.exec(
                select(AppSetting).where(AppSetting.key.in_(AI_SETTING_KEYS))
            ).all()
        }
        for key, value in values.items():
            row = rows.get(key)
            if row is None:
                row = AppSetting(key=key)
            row.value = value
            row.updated_at = utcnow()
            session.add(row)
        session.commit()

    return {"ok": True}
