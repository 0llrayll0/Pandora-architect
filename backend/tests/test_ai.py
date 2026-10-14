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
- heurística de ciclo: grafo com ciclo → finding ``cycle`` ``high``; DAG → nenhum.
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
from app.routers.ai import MAX_LIST_ITEMS, MAX_TEXT_CHARS, _coerce_report, _extract_json, _persist

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

    assert _coerce_report({"strengths": []}) is None
    assert _coerce_report({"executive_summary": "   "}) is None


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
