"""Testes do Arquiteto IA (Fase 6): relatório, Ollama mockado e limites.

Cobertura:
- GET antes do POST → 404 ``report_not_found``;
- POST com Ollama mockado (JSON válido) → 200 + ``ollama_used: true``;
- POST com Ollama falhando (timeout/exceção) → 200 + ``ollama_used: false``
  com heurísticas intactas (nunca 500 por causa do LLM);
- POST com resposta não-JSON → fallback heurístico;
- upsert por run (regenerar atualiza, não duplica) + corrida no ``_persist``;
- POST inexistente → 404; POST em run não ``completed`` → 400 ``run_not_active``;
- ``_extract_json`` / ``_coerce_report`` / limites de tamanho;
- heurística de ciclo: grafo com ciclo → finding ``cycle`` ``high``; DAG → nenhum;
- configuração do provedor (GET/PUT ``/api/ai/config``): a API key nunca é
  exposta, ``api_key`` null/vazia preserva a chave existente;
- provedor openai-compatible: ``chat/completions`` com Bearer e fallback
  sem chave (nenhuma chamada de rede → heurísticas);
- provedores Anthropic (``/v1/messages``) e Gemini (``:generateContent``):
  extração do texto da resposta, defaults de base_url/modelo e PUT aceito;
- PUT com provider inválido → 400 ``invalid_provider``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import networkx as nx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.analysis.heuristics import build_findings
from app.config import get_settings
from app.db import get_engine
from app.models import ArchitectureReport, RunState
from app.routers.ai import (
    MAX_LIST_ITEMS,
    MAX_TEXT_CHARS,
    SYSTEM_PROMPT,
    AiConfig,
    _call_anthropic,
    _call_gemini,
    _coerce_report,
    _extract_json,
    _persist,
)

# ---------------------------------------------------------------------------
# Mock do Ollama (httpx.Client falso — nunca fala com a rede)
# ---------------------------------------------------------------------------

VALID_LLM_JSON = json.dumps(
    {
        "executive_summary": "Resumo gerado pelo modelo local.",
        "strengths": ["Modular", "Testável"],
        "risks": [
            {
                "title": "Ciclo entre arquivos",
                "severity": "high",
                "description": "cycle1 e cycle2 se importam mutuamente.",
            }
        ],
        "action_plan": [
            {
                "action": "Quebrar o ciclo extraindo uma interface",
                "justification": "dependência circular",
                "impact": "Alto",
            }
        ],
    }
)


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._body


class _FakeClient:
    """httpx.Client falso: devolve ``response_text`` ou levanta ``error``."""

    def __init__(self, response_text: str = "", error: Exception | None = None) -> None:
        self._response_text = response_text
        self._error = error

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        if self._error is not None:
            raise self._error
        return _FakeResponse({"response": self._response_text})


def _mock_ollama(
    monkeypatch: pytest.MonkeyPatch, response_text: str = "", error: Exception | None = None
) -> None:
    """Substitui ``httpx.Client``: o TestClient já instanciado não é afetado."""

    def _factory(*args: Any, **kwargs: Any) -> _FakeClient:
        return _FakeClient(response_text=response_text, error=error)

    monkeypatch.setattr(httpx, "Client", _factory)


def _post(client: Any, run_id: int) -> Any:
    return client.post(f"/api/ai/runs/{run_id}/report", json={})


# ---------------------------------------------------------------------------
# Endpoints: GET/POST
# ---------------------------------------------------------------------------


def test_get_report_before_generation_is_404(client, analyzed_project) -> None:
    _project, run_id = analyzed_project
    resp = client.get(f"/api/ai/runs/{run_id}/report")
    assert resp.status_code == 404
    assert resp.json()["code"] == "report_not_found"


def test_post_report_with_ollama_success(client, analyzed_project, monkeypatch) -> None:
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, VALID_LLM_JSON)

    resp = _post(client, run_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama_used"] is True
    assert body["ollama_model"] == get_settings().ollama_model
    assert body["executive_summary"] == "Resumo gerado pelo modelo local."
    assert body["strengths"] == ["Modular", "Testável"]
    assert body["risks"][0]["title"] == "Ciclo entre arquivos"
    assert body["action_plan"][0]["action"].startswith("Quebrar o ciclo")
    # heurísticas determinísticas continuam presentes junto com a narrativa
    assert body["findings"]

    cached = client.get(f"/api/ai/runs/{run_id}/report")
    assert cached.status_code == 200
    assert cached.json()["executive_summary"] == body["executive_summary"]


def test_post_report_ollama_failure_falls_back_to_heuristics(
    client, analyzed_project, monkeypatch
) -> None:
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, error=httpx.ConnectError("ollama fora do ar"))

    resp = _post(client, run_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama_used"] is False
    assert body["ollama_model"] is None
    # heurísticas intactas: sample tem ciclo1 ↔ ciclo2 → risk de ciclo
    assert body["executive_summary"]
    assert body["findings"]
    assert any(r["severity"] == "high" for r in body["risks"])


def test_post_report_ollama_timeout_falls_back_to_heuristics(
    client, analyzed_project, monkeypatch
) -> None:
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, error=httpx.TimeoutException("estourou 60s"))

    resp = _post(client, run_id)
    assert resp.status_code == 200
    assert resp.json()["ollama_used"] is False


def test_post_report_ollama_non_json_falls_back(
    client, analyzed_project, monkeypatch
) -> None:
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, "Desculpe, não consegui gerar o JSON pedido.")

    resp = _post(client, run_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama_used"] is False
    assert body["executive_summary"]
    assert body["findings"]


def test_post_twice_updates_report_instead_of_duplicating(
    client, analyzed_project, monkeypatch
) -> None:
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, VALID_LLM_JSON)

    first = _post(client, run_id)
    second = _post(client, run_id)
    assert first.status_code == 200
    assert second.status_code == 200

    with Session(get_engine()) as session:
        rows = session.exec(
            select(ArchitectureReport).where(ArchitectureReport.run_id == run_id)
        ).all()
    assert len(rows) == 1
    assert rows[0].payload["executive_summary"] == second.json()["executive_summary"]

    cached = client.get(f"/api/ai/runs/{run_id}/report").json()
    assert cached["executive_summary"] == second.json()["executive_summary"]


def test_post_report_missing_run_is_404(client) -> None:
    resp = _post(client, 999_999)
    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"


@pytest.mark.parametrize(
    "state",
    [
        RunState.PENDING.value,
        RunState.RUNNING.value,
        RunState.FAILED.value,
        RunState.CANCELLED.value,
    ],
)
def test_post_report_run_not_completed_is_400(
    client, sample_project: Path, make_project, make_run, state: str
) -> None:
    project = make_project(sample_project)
    run_id = make_run(project, state=state)

    resp = _post(client, run_id)
    assert resp.status_code == 400
    assert resp.json()["code"] == "run_not_active"


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('``` json\n{"a": 1}\n```', {"a": 1}),  # fence com espaço antes do tipo
        ('```\n{"a": 1}\n```', {"a": 1}),  # fence sem tipo
        ('texto antes {"a": 1} meio {"b": 2} depois', {"a": 1}),  # dois objetos → 1º
        ('{"a": 1} e sobra texto', {"a": 1}),
        ("nada de json aqui", None),
        ("[1, 2, 3]", None),  # lista não é objeto
        ("", None),
        ("   ", None),
    ],
)
def test_extract_json_variants(text: str, expected: dict[str, Any] | None) -> None:
    assert _extract_json(text) == expected


# ---------------------------------------------------------------------------
# _coerce_report
# ---------------------------------------------------------------------------


def test_coerce_report_normalizes_malformed_payload() -> None:
    raw: dict[str, Any] = {
        "executive_summary": "  ok  ",
        "strengths": "apenas uma string",
        "risks": [
            "não é um dict",
            {"title": "R1", "severity": "invalida", "description": "d"},
            {"severity": "HIGH"},  # title default + severidade normalizada
        ],
        "action_plan": "não é lista",
    }
    out = _coerce_report(raw)
    assert out is not None
    assert out["executive_summary"] == "ok"
    assert out["strengths"] == ["apenas uma string"]
    assert len(out["risks"]) == 2
    assert out["risks"][0] == {"title": "R1", "severity": "low", "description": "d"}
    assert out["risks"][1]["title"] == "Risco"
    assert out["risks"][1]["severity"] == "high"
    assert out["action_plan"] == []


def test_coerce_report_empty_and_missing_fields() -> None:
    out = _coerce_report(
        {
            "executive_summary": "ok",
            "strengths": [],
            "risks": None,
            "action_plan": None,
        }
    )
    assert out is not None
    assert out["strengths"] == []
    assert out["risks"] == []
    assert out["action_plan"] == []
    # sem a seção no JSON do LLM → ``None`` (o backend preenche depois)
    assert out["dependencies"] is None

    assert _coerce_report({"strengths": []}) is None
    assert _coerce_report({"executive_summary": "   "}) is None


def test_coerce_report_normalizes_dependencies() -> None:
    """Itens malformados caem fora; tipos e limites são aplicados."""
    out = _coerce_report(
        {
            "executive_summary": "ok",
            "dependencies": {
                "internal": [
                    {"name": "m" * (MAX_TEXT_CHARS + 10), "imported_by": ["a.py", 2, ""], "out_degree": "7"},
                    "não é dict",
                    {"imported_by": ["x.py"]},  # sem nome → descartado
                    None,
                ],
                "external": [
                    {"name": "numpy", "import_count": "3"},  # is_stdlib ausente → calculado
                    {"name": "os", "import_count": 1, "is_stdlib": True},
                    {"name": "cv2", "import_count": "abc"},  # inteiro inválido → 0
                    {"sem_nome": 1},
                ],
                "recommendations": ["rec 1", "", 42, "rec 2"],
            },
        }
    )
    assert out is not None
    deps = out["dependencies"]
    assert deps is not None

    assert [item["name"] for item in deps["internal"]] == ["m" * MAX_TEXT_CHARS]
    assert deps["internal"][0]["imported_by"] == ["a.py", "2"]
    assert deps["internal"][0]["out_degree"] == 7

    assert deps["external"] == [
        {"name": "numpy", "import_count": 3, "is_stdlib": False},
        {"name": "os", "import_count": 1, "is_stdlib": True},
        {"name": "cv2", "import_count": 0, "is_stdlib": False},
    ]
    assert deps["recommendations"] == ["rec 1", "42", "rec 2"]


def test_coerce_report_rejects_non_dict_dependencies() -> None:
    out = _coerce_report({"executive_summary": "ok", "dependencies": "lista não é dict"})
    assert out is not None
    assert out["dependencies"] is None


# ---------------------------------------------------------------------------
# Limites de tamanho (persistência)
# ---------------------------------------------------------------------------


def test_report_limits_lists_and_texts(client, analyzed_project, monkeypatch) -> None:
    _project, run_id = analyzed_project
    oversized = {
        "executive_summary": "x" * (MAX_TEXT_CHARS + 500),
        "strengths": [f"força {i}" for i in range(MAX_LIST_ITEMS + 30)],
        "risks": [
            {"title": f"r{i}", "severity": "low", "description": "y" * (MAX_TEXT_CHARS + 10)}
            for i in range(MAX_LIST_ITEMS + 30)
        ],
        "action_plan": [
            {"action": "a" * (MAX_TEXT_CHARS + 10), "justification": "j", "impact": "i"}
            for _ in range(10)
        ],
    }
    _mock_ollama(monkeypatch, json.dumps(oversized))

    body = _post(client, run_id).json()
    assert len(body["strengths"]) == MAX_LIST_ITEMS
    assert len(body["risks"]) == MAX_LIST_ITEMS
    assert len(body["executive_summary"]) == MAX_TEXT_CHARS
    assert all(len(r["description"]) <= MAX_TEXT_CHARS for r in body["risks"])
    assert len(body["action_plan"]) <= 5
    assert all(len(step["action"]) <= MAX_TEXT_CHARS for step in body["action_plan"])


# ---------------------------------------------------------------------------
# Seção de dependências
# ---------------------------------------------------------------------------


def test_report_dependencies_section_from_heuristics(
    client, analyzed_project, monkeypatch
) -> None:
    """Sem LLM: a seção vem do banco (interna + externa não vazias)."""
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, error=httpx.ConnectError("ollama fora do ar"))

    body = _post(client, run_id).json()
    deps = body["dependencies"]

    assert isinstance(deps["internal"], list) and deps["internal"]
    assert isinstance(deps["external"], list) and deps["external"]
    assert isinstance(deps["recommendations"], list)
    assert all(isinstance(item, str) for item in deps["recommendations"])

    internal = {entry["name"]: entry for entry in deps["internal"]}
    assert {"cycle1", "cycle2", "pkg_a.mod", "pkg_b.service", "pkg_b.x"} <= set(internal)
    assert internal["pkg_a.mod"]["out_degree"] == 2
    assert set(internal["pkg_a.mod"]["imported_by"]) == {"main.py", "pkg_a/util.py"}
    assert all(isinstance(entry["out_degree"], int) for entry in deps["internal"])

    external = {entry["name"]: entry for entry in deps["external"]}
    assert external["os"]["is_stdlib"] is True
    assert external["requests"]["is_stdlib"] is False
    assert external["requests"]["import_count"] == 1
    # terceiros vêm antes da stdlib (a UI exibe só os não-stdlib)
    assert deps["external"][0]["name"] == "requests"
    # pacote de terceiros usado em 1 arquivo gera recomendação heurística
    assert any("requests" in item for item in deps["recommendations"])

    # a seção também fica no cache (GET devolve o mesmo payload)
    cached = client.get(f"/api/ai/runs/{run_id}/report").json()
    assert cached["dependencies"]["internal"]


def test_report_llm_dependencies_are_normalized(client, analyzed_project, monkeypatch) -> None:
    """LLM devolve ``dependencies`` → recommendations entram, listas continuam do banco."""
    _project, run_id = analyzed_project
    payload = json.loads(VALID_LLM_JSON)
    payload["dependencies"] = {
        "internal": [
            {"name": "m" * (MAX_TEXT_CHARS + 50), "imported_by": [1, "a.py", ""], "out_degree": "7"},
            "entradas inválidas são descartadas",
        ],
        "external": [{"name": "numpy", "import_count": "2"}],
        "recommendations": ["comentário do modelo", ""]
        + [f"recomendação {i}" for i in range(MAX_LIST_ITEMS * 2)],
    }
    _mock_ollama(monkeypatch, json.dumps(payload))

    body = _post(client, run_id).json()
    deps = body["dependencies"]

    assert deps["recommendations"][0] == "comentário do modelo"
    assert len(deps["recommendations"]) <= MAX_LIST_ITEMS
    assert all(isinstance(item, str) for item in deps["recommendations"])
    # listas estruturadas vêm do banco (dado real), normalizadas e limitadas
    assert {entry["name"] for entry in deps["external"]} >= {"os", "requests"}
    assert all(len(entry["name"]) <= MAX_TEXT_CHARS for entry in deps["internal"])


def test_report_without_llm_dependencies_fills_section_from_backend(
    client, analyzed_project, monkeypatch
) -> None:
    """LLM não devolve ``dependencies`` → o backend preenche a seção na mesma."""
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, VALID_LLM_JSON)

    body = _post(client, run_id).json()
    assert body["ollama_used"] is True
    assert body["dependencies"]["internal"]
    assert body["dependencies"]["external"]
    assert all(isinstance(item, str) for item in body["dependencies"]["recommendations"])


# ---------------------------------------------------------------------------
# Persistência idempotente (corrida no upsert)
# ---------------------------------------------------------------------------


def test_persist_race_falls_back_to_update(analyzed_project) -> None:
    """Primeiro commit estoura IntegrityError → refaz como UPDATE (1 linha)."""
    project, run_id = analyzed_project

    with Session(get_engine()) as session:
        _persist(
            session, run_id, project.id or 0, {"v": 1}, ollama_used=False, ollama_model=""
        )

    with Session(get_engine()) as session:
        original_commit = session.commit
        calls = {"n": 0}

        def racing_commit() -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
            original_commit()

        session.commit = racing_commit  # type: ignore[method-assign]
        _persist(
            session, run_id, project.id or 0, {"v": 2}, ollama_used=False, ollama_model=""
        )

        rows = session.exec(
            select(ArchitectureReport).where(ArchitectureReport.run_id == run_id)
        ).all()
    assert len(rows) == 1
    assert rows[0].payload == {"v": 2}


# ---------------------------------------------------------------------------
# Heurísticas: ciclo
# ---------------------------------------------------------------------------


def _file_graph(*edges: tuple[str, str]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for source, target in edges:
        graph.add_node(f"file:{source}", type="file", label=source)
        graph.add_node(f"file:{target}", type="file", label=target)
        graph.add_edge(f"file:{source}", f"file:{target}", type="imports")
    return graph


def _metrics_with_cycles(count: int, signatures: list[list[str]]) -> dict[str, Any]:
    return {
        "totals": {"nodes": 2, "edges": count, "density": 1.0, "largest_scc": 2 if count else 1},
        "cycles": {"available": True, "count": count, "signatures": signatures},
        "hotspots": [],
    }


def test_build_findings_cycle_is_high_severity() -> None:
    graph = _file_graph(("a.py", "b.py"), ("b.py", "a.py"))
    metrics = _metrics_with_cycles(1, [["file:a.py", "file:b.py"]])

    findings = build_findings(graph, metrics)
    cycle = next(f for f in findings if f["type"] == "cycle")
    assert cycle["severity"] == "high"


def test_build_findings_dag_has_no_cycle() -> None:
    graph = _file_graph(("a.py", "b.py"), ("b.py", "c.py"))
    metrics = _metrics_with_cycles(0, [])

    findings = build_findings(graph, metrics)
    assert all(f["type"] != "cycle" for f in findings)


def test_post_report_findings_include_cycle(
    client, analyzed_project, monkeypatch
) -> None:
    """Integração: o sample tem ciclo1 ↔ ciclo2 → finding cycle/high na resposta."""
    _project, run_id = analyzed_project
    _mock_ollama(monkeypatch, error=httpx.ConnectError("off"))

    body = _post(client, run_id).json()
    cycle = next(f for f in body["findings"] if f["type"] == "cycle")
    assert cycle["severity"] == "high"


# ---------------------------------------------------------------------------
# Configuração do provedor de IA (GET/PUT /api/ai/config)
# ---------------------------------------------------------------------------

#: Chave falsa só para o teste — nenhum valor real é gravado aqui.
FAKE_KEY = "sk-TESTE-fake-000"
FAKE_KEY_2 = "sk-TESTE-fake-111"


def _put_config(client: Any, **overrides: Any) -> Any:
    payload = {"provider": "ollama", "base_url": "", "model": "", "api_key": None}
    payload.update(overrides)
    return client.put("/api/ai/config", json=payload)


def test_get_ai_config_reports_provider_without_exposing_key(client) -> None:
    resp = client.get("/api/ai/config")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"provider", "base_url", "model", "has_api_key"}
    assert body["provider"] == "ollama"
    assert body["base_url"] == get_settings().ollama_url
    assert body["model"] == get_settings().ollama_model
    assert body["has_api_key"] is False


def test_get_ai_config_never_returns_api_key(client) -> None:
    _put_config(client, provider="openai", model="gpt-4o-mini", api_key=FAKE_KEY)

    resp = client.get("/api/ai/config")
    body = resp.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert FAKE_KEY not in resp.text  # nem parcialmente


def test_put_ai_config_updates_provider_and_model(client) -> None:
    resp = _put_config(
        client,
        provider="openai",
        base_url="https://example.test/v1",
        model="gpt-4o-mini",
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    body = client.get("/api/ai/config").json()
    assert body["provider"] == "openai"
    assert body["base_url"] == "https://example.test/v1"
    assert body["model"] == "gpt-4o-mini"
    assert body["has_api_key"] is False


def test_put_ai_config_null_api_key_keeps_existing_key(client) -> None:
    assert _put_config(client, provider="ollama", api_key=FAKE_KEY).json() == {"ok": True}
    assert client.get("/api/ai/config").json()["has_api_key"] is True

    # api_key None → mantém a chave e atualiza o resto
    resp = _put_config(
        client,
        provider="custom",
        base_url="https://llm.test/v1",
        model="meu-modelo",
        api_key=None,
    )
    assert resp.json() == {"ok": True}

    body = client.get("/api/ai/config").json()
    assert body["provider"] == "custom"
    assert body["model"] == "meu-modelo"
    assert body["has_api_key"] is True
    assert FAKE_KEY not in json.dumps(body)

    # api_key vazia também preserva a chave existente
    _put_config(client, provider="custom", api_key="")
    assert client.get("/api/ai/config").json()["has_api_key"] is True


def test_put_ai_config_new_api_key_flips_has_api_key(client) -> None:
    assert client.get("/api/ai/config").json()["has_api_key"] is False

    _put_config(client, provider="openai", model="gpt-4o-mini", api_key=FAKE_KEY)
    assert client.get("/api/ai/config").json()["has_api_key"] is True

    # chave nova substitui a anterior
    _put_config(client, provider="openai", model="gpt-4o-mini", api_key=FAKE_KEY_2)
    body = client.get("/api/ai/config").json()
    assert body["has_api_key"] is True
    assert FAKE_KEY_2 not in json.dumps(body)
    assert FAKE_KEY not in json.dumps(body)


def test_put_ai_config_invalid_provider_is_400(client) -> None:
    resp = _put_config(client, provider="claude")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_provider"
    assert client.get("/api/ai/config").json()["provider"] == "ollama"


@pytest.mark.parametrize("provider", ["invalido", "não-existe", ""])
def test_put_ai_config_unknown_provider_is_400(client, provider: str) -> None:
    """Só o conjunto fechado de provedores é aceito (400 ``invalid_provider``)."""
    resp = _put_config(client, provider=provider)
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_provider"
    assert client.get("/api/ai/config").json()["provider"] == "ollama"


def test_put_ai_config_accepts_anthropic_and_exposes_defaults(client) -> None:
    resp = _put_config(client, provider="anthropic")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    body = client.get("/api/ai/config").json()
    assert body["provider"] == "anthropic"
    assert body["base_url"] == "https://api.anthropic.com"
    assert body["model"] == "claude-sonnet-4-20250514"
    assert "api_key" not in body


def test_put_ai_config_accepts_gemini_and_exposes_defaults(client) -> None:
    resp = _put_config(client, provider="gemini")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    body = client.get("/api/ai/config").json()
    assert body["provider"] == "gemini"
    assert body["base_url"] == "https://generativelanguage.googleapis.com/v1beta"
    assert body["model"] == "gemini-2.0-flash"
    assert "api_key" not in body


# ---------------------------------------------------------------------------
# Provedores Anthropic e Gemini: chamada, extração e fallback
# ---------------------------------------------------------------------------


def _provider_config(provider: str) -> AiConfig:
    """Config efetiva como ``_resolve_ai_config`` devolve (base/modelo default)."""
    if provider == "anthropic":
        return AiConfig(
            provider="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-20250514",
            api_key=FAKE_KEY,
        )
    return AiConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.0-flash",
        api_key=FAKE_KEY,
    )


def _mock_json_client(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], error: Exception | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Instala um httpx.Client falso que devolve ``body`` e grava as chamadas."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class _JsonClient(_FakeClient):
        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            calls.append((url, kwargs))
            if error is not None:
                raise error
            return _FakeResponse(body)

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _JsonClient())
    return calls


def test_call_anthropic_extracts_content_text(monkeypatch) -> None:
    """``content[0].text`` vira o relatório (system separado do user prompt)."""
    calls = _mock_json_client(
        monkeypatch, {"content": [{"type": "text", "text": VALID_LLM_JSON}]}
    )

    out = _call_anthropic("prompt do usuario", _provider_config("anthropic"))
    assert out is not None
    assert out["executive_summary"] == "Resumo gerado pelo modelo local."
    assert out["risks"][0]["title"] == "Ciclo entre arquivos"

    url, kwargs = calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert kwargs["headers"]["x-api-key"] == FAKE_KEY
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["headers"]["content-type"] == "application/json"
    sent = kwargs["json"]
    assert sent["model"] == "claude-sonnet-4-20250514"
    assert sent["max_tokens"] == 4096
    assert sent["system"] == SYSTEM_PROMPT
    assert sent["messages"] == [{"role": "user", "content": "prompt do usuario"}]


def test_call_anthropic_picks_first_text_block(monkeypatch) -> None:
    """Blocos não-texto (thinking) antes do texto são ignorados."""
    _mock_json_client(
        monkeypatch,
        {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": VALID_LLM_JSON},
            ]
        },
    )

    out = _call_anthropic("p", _provider_config("anthropic"))
    assert out is not None
    assert out["executive_summary"] == "Resumo gerado pelo modelo local."


def test_call_anthropic_without_key_or_on_error_returns_none(monkeypatch) -> None:
    calls = _mock_json_client(monkeypatch, {"content": [{"type": "text", "text": "{}"}]})

    sem_chave = AiConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-20250514",
        api_key="",
    )
    assert _call_anthropic("p", sem_chave) is None
    assert calls == []  # sem chave não há chamada de rede

    # resposta malformada / exceção → None (nunca 500)
    assert _call_anthropic("p", _provider_config("anthropic")) is None

    _mock_json_client(monkeypatch, {}, error=httpx.TimeoutException("estourou 60s"))
    assert _call_anthropic("p", _provider_config("anthropic")) is None


def test_call_gemini_extracts_candidate_text(monkeypatch) -> None:
    """``candidates[0].content.parts[0].text`` vira o relatório."""
    calls = _mock_json_client(
        monkeypatch,
        {"candidates": [{"content": {"role": "model", "parts": [{"text": VALID_LLM_JSON}]}}]},
    )

    out = _call_gemini("prompt do usuario", _provider_config("gemini"))
    assert out is not None
    assert out["executive_summary"] == "Resumo gerado pelo modelo local."
    assert out["action_plan"][0]["action"].startswith("Quebrar o ciclo")

    url, kwargs = calls[0]
    assert url == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash"
        f":generateContent?key={FAKE_KEY}"
    )
    sent = kwargs["json"]
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "prompt do usuario"}]}]
    assert sent["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    assert sent["generationConfig"] == {
        "temperature": 0.2,
        "responseMimeType": "application/json",
    }


def test_call_gemini_without_key_or_on_error_returns_none(monkeypatch) -> None:
    calls = _mock_json_client(monkeypatch, {"candidates": [{"content": {"parts": []}}]})

    sem_chave = AiConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.0-flash",
        api_key="",
    )
    assert _call_gemini("p", sem_chave) is None
    assert calls == []

    # candidates vazio / sem texto → None
    assert _call_gemini("p", _provider_config("gemini")) is None

    _mock_json_client(monkeypatch, {}, error=httpx.ConnectError("sem rede"))
    assert _call_gemini("p", _provider_config("gemini")) is None


def test_report_with_anthropic_provider_uses_llm(
    client, analyzed_project, monkeypatch
) -> None:
    """Integração: provider anthropic → POST /v1/messages e ``ollama_used: true``."""
    _project, run_id = analyzed_project
    _put_config(client, provider="anthropic", api_key=FAKE_KEY)

    _mock_json_client(
        monkeypatch, {"content": [{"type": "text", "text": VALID_LLM_JSON}]}
    )
    body = _post(client, run_id).json()
    assert body["ollama_used"] is True
    assert body["ollama_model"] == "claude-sonnet-4-20250514"
    assert body["executive_summary"] == "Resumo gerado pelo modelo local."


def test_report_with_gemini_provider_uses_llm(
    client, analyzed_project, monkeypatch
) -> None:
    """Integração: provider gemini → :generateContent e ``ollama_used: true``."""
    _project, run_id = analyzed_project
    _put_config(client, provider="gemini", api_key=FAKE_KEY)

    _mock_json_client(
        monkeypatch,
        {"candidates": [{"content": {"parts": [{"text": VALID_LLM_JSON}]}}]},
    )
    body = _post(client, run_id).json()
    assert body["ollama_used"] is True
    assert body["ollama_model"] == "gemini-2.0-flash"
    assert body["executive_summary"] == "Resumo gerado pelo modelo local."


# ---------------------------------------------------------------------------
# Provedores OpenAI-compatible: chamada e fallback sem chave
# ---------------------------------------------------------------------------


def test_report_openai_without_key_never_calls_network(
    client, analyzed_project, monkeypatch
) -> None:
    """Sem chave → ``_call_llm`` devolve None sem tocar na rede (só heurística)."""
    _project, run_id = analyzed_project
    _put_config(
        client,
        provider="openai",
        base_url="https://example.test/v1",
        model="gpt-4o-mini",
    )

    calls: list[Any] = []

    def _factory(*args: Any, **kwargs: Any) -> _FakeClient:
        calls.append(kwargs)
        return _FakeClient(response_text=VALID_LLM_JSON)

    monkeypatch.setattr(httpx, "Client", _factory)

    resp = _post(client, run_id)
    assert resp.status_code == 200
    assert resp.json()["ollama_used"] is False
    assert calls == []


def test_report_openai_with_key_posts_chat_completions(
    client, analyzed_project, monkeypatch
) -> None:
    _project, run_id = analyzed_project
    _put_config(
        client,
        provider="openai",
        base_url="https://example.test/v1/",
        model="gpt-4o-mini",
        api_key=FAKE_KEY,
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    class _OpenAIClient(_FakeClient):
        def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            calls.append((url, kwargs))
            return _FakeResponse({"choices": [{"message": {"content": VALID_LLM_JSON}}]})

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _OpenAIClient())

    body = _post(client, run_id).json()
    assert body["ollama_used"] is True
    assert body["ollama_model"] == "gpt-4o-mini"
    assert body["executive_summary"] == "Resumo gerado pelo modelo local."

    url, kwargs = calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    sent = kwargs["json"]
    assert sent["model"] == "gpt-4o-mini"
    assert sent["temperature"] == 0.2
    assert sent["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
