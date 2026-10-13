"""Testes da API HTTP (TestClient) — CRUD, análise, grafo e explorador."""

from __future__ import annotations

from pathlib import Path

from app.analysis.pipeline import wait_for_run
from app.models import Project


def _create(client, path: Path, *, name: str = "demo") -> dict:
    resp = client.post("/api/projects", json={"name": name, "path": str(path)})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Health / meta / rotas
# ---------------------------------------------------------------------------


def test_health_ok(client) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "pandora-architect"
    assert body["database"] == "ok"
    assert body["projects"] == 0


def test_meta(client) -> None:
    body = client.get("/api/meta").json()
    assert body["service"] == "pandora-architect"
    assert body["version"] == "0.1.0"
    assert body["platform"]


def test_root_reports_service_info(client) -> None:
    body = client.get("/").json()
    assert body["service"] == "pandora-architect"
    assert body["api"] == "/api"


def test_unknown_api_route_is_json_404(client) -> None:
    resp = client.get("/api/rota_que_nao_existe")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# ---------------------------------------------------------------------------
# CRUD de projetos
# ---------------------------------------------------------------------------


def test_create_project(client, sample_project: Path) -> None:
    body = _create(client, sample_project)
    assert body["id"] > 0
    assert body["name"] == "demo"
    assert body["path"] == str(sample_project.resolve())
    assert body["run_count"] == 0
    assert body["last_run"] is None


def test_create_project_derives_name_from_path(client, sample_project: Path) -> None:
    body = _create(client, sample_project, name="")
    assert body["name"] == "proj"  # nome do diretório


def test_create_project_duplicate_conflicts(client, sample_project: Path) -> None:
    _create(client, sample_project)
    resp = client.post("/api/projects", json={"name": "dup", "path": str(sample_project)})
    assert resp.status_code == 409
    assert resp.json()["code"] == "project_exists"


def test_create_project_rejects_outside_allowed_dirs(client) -> None:
    resp = client.post("/api/projects", json={"name": "etc", "path": "/etc"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "path_not_allowed"


def test_create_project_rejects_missing_path(client, tmp_path: Path) -> None:
    resp = client.post(
        "/api/projects", json={"name": "x", "path": str(tmp_path / "fantasma")}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "path_not_found"


def test_create_project_rejects_file_path(client, tmp_path: Path) -> None:
    target = tmp_path / "arquivo.txt"
    target.write_text("x", encoding="utf-8")
    resp = client.post("/api/projects", json={"name": "x", "path": str(target)})
    assert resp.status_code == 403
    assert resp.json()["code"] == "not_a_directory"


def test_list_projects_empty_and_after_create(client, sample_project: Path) -> None:
    assert client.get("/api/projects").json() == []
    _create(client, sample_project)
    items = client.get("/api/projects").json()
    assert len(items) == 1
    assert items[0]["name"] == "demo"


def test_read_project_missing_404(client) -> None:
    resp = client.get("/api/projects/9999")
    assert resp.status_code == 404
    assert resp.json()["code"] == "project_not_found"


def test_patch_project(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    resp = client.patch(f"/api/projects/{project['id']}", json={"name": "renomeado"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renomeado"


def test_delete_project(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert client.get("/api/projects").json() == []


def test_validation_error_envelope(client) -> None:
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "path" in body["detail"]


# ---------------------------------------------------------------------------
# Análise ponta a ponta via API
# ---------------------------------------------------------------------------


def test_full_analysis_flow(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    pid = project["id"]

    resp = client.post(f"/api/projects/{pid}/analyze", json={})
    assert resp.status_code == 202
    rid = resp.json()["id"]
    assert resp.json()["state"] == "pending"

    assert wait_for_run(rid) is True

    status = client.get(f"/api/analysis/runs/{rid}").json()
    assert status["state"] == "completed"
    assert status["progress"] == 100.0
    assert status["running"] is False
    assert status["files_processed"] == 10
    assert status["files_failed"] == 1
    assert status["symbols_count"] == 15
    assert status["dependencies_count"] == 9
    assert status["modules_count"] == 10
    assert status["errors_count"] == 1

    # histórico do projeto
    runs = client.get(f"/api/projects/{pid}/runs").json()
    assert len(runs) == 1 and runs[0]["id"] == rid
    latest = client.get(f"/api/projects/{pid}/latest").json()
    assert latest["id"] == rid
    assert client.get(f"/api/projects/{pid}/analysis/{rid}").status_code == 200

    # summary
    summary = client.get(f"/api/analysis/runs/{rid}/summary").json()
    assert summary["metrics"]["files_scanned"] == 10.0
    assert summary["metrics"]["parse_errors"] == 1.0
    assert summary["metrics"]["dependencies_confirmed"] == 6.0
    assert summary["metrics"]["dependencies_external"] == 2.0
    assert summary["metrics"]["dependencies_unresolved"] == 1.0
    assert summary["files"] == {"total": 10, "parse_errors": 1}
    assert summary["project"]["name"] == "demo"

    # arquivos
    files = client.get(f"/api/analysis/runs/{rid}/files").json()
    assert files["total"] == 10
    broken = next(f for f in files["items"] if f["path"] == "broken.py")
    assert broken["parse_ok"] is False
    assert "SyntaxError" in broken["parse_error"]
    assert files["items"] == sorted(files["items"], key=lambda f: f["path"])

    # símbolos
    symbols = client.get(f"/api/analysis/runs/{rid}/symbols").json()
    assert symbols["total"] == 15
    functions = client.get(
        f"/api/analysis/runs/{rid}/symbols", params={"kind": "function"}
    ).json()
    assert functions["total"] == 6
    main_fn = next(s for s in functions["items"] if s["name"] == "main")
    assert main_fn["complexity"] == 4
    search = client.get(f"/api/analysis/runs/{rid}/symbols", params={"q": "beta"}).json()
    assert search["total"] == 1

    # dependências
    deps = client.get(f"/api/analysis/runs/{rid}/dependencies").json()
    assert deps["total"] == 9
    for classification, expected in (("confirmed", 6), ("external", 2), ("unresolved", 1)):
        resp = client.get(
            f"/api/analysis/runs/{rid}/dependencies",
            params={"classification": classification},
        )
        assert resp.json()["total"] == expected, classification

    # métricas
    metrics = client.get(f"/api/analysis/runs/{rid}/metrics").json()
    assert metrics["project"]["functions"] == 6.0
    assert metrics["project"]["classes"] == 0.0
    assert metrics["project"]["max_complexity"] == 4.0
    assert metrics["project"]["avg_complexity"] == 1.5
    assert metrics["hotspots"][0]["path"] == "main.py"
    assert metrics["hotspots"][0]["max_complexity"] == 4.0

    # grafo + ciclos
    graph = client.get(f"/api/graph/{rid}").json()
    assert graph["run_id"] == rid
    assert graph["counts"]["nodes"] == 38
    assert graph["counts"]["edges"] == 34
    assert graph["counts"]["is_dag"] is False
    assert graph["counts"]["nodes_by_type"]["symbol"] == 15

    no_symbols = client.get(f"/api/graph/{rid}", params={"include_symbols": "false"}).json()
    assert "symbol" not in no_symbols["counts"]["nodes_by_type"]
    assert no_symbols["counts"]["nodes"] == 23

    cycles = client.get(f"/api/graph/{rid}/cycles").json()
    assert cycles["count"] == 1
    assert cycles["cycles"] == [["file:cycle1.py", "file:cycle2.py"]]

    # explorador
    tree = client.get(f"/api/projects/{pid}/explorer", params={"depth": 2}).json()
    assert tree["analyzed_paths"] == 10
    names = [e["name"] for e in tree["entries"]]
    assert "main.py" in names and "pkg_a" in names
    main_entry = next(e for e in tree["entries"] if e["name"] == "main.py")
    assert main_entry["analyzed"] is True
    pkg_entry = next(e for e in tree["entries"] if e["name"] == "pkg_a")
    assert pkg_entry["type"] == "dir"

    source = client.get(
        f"/api/projects/{pid}/explorer/file", params={"path": "main.py"}
    ).json()
    assert source["language"] == "python"
    assert source["parse_ok"] is True
    assert "def main" in source["content"]
    assert {s["kind"] for s in source["symbols"]} == {"module", "function"}


def test_second_analyze_allowed_after_completion(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    rid = client.post(f"/api/projects/{project['id']}/analyze", json={}).json()["id"]
    assert wait_for_run(rid) is True

    # run concluída não bloqueia uma nova análise
    resp = client.post(f"/api/projects/{project['id']}/analyze", json={})
    assert resp.status_code == 202
    rid2 = resp.json()["id"]
    assert wait_for_run(rid2) is True
    assert client.get(f"/api/analysis/runs/{rid2}").json()["state"] == "completed"


def test_delete_project_with_completed_run(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    rid = client.post(f"/api/projects/{project['id']}/analyze", json={}).json()["id"]
    assert wait_for_run(rid) is True
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/analysis/runs/{rid}").status_code == 404


# ---------------------------------------------------------------------------
# Explorador (segurança e erros)
# ---------------------------------------------------------------------------


def test_explorer_traversal_rejected(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    resp = client.get(
        f"/api/projects/{project['id']}/explorer/file",
        params={"path": "../outside_target.py"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "path_not_allowed"


def test_explorer_tree_missing_path_404(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    resp = client.get(
        f"/api/projects/{project['id']}/explorer", params={"path": "nao_existe"}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "path_not_found"


def test_explorer_tree_on_file_is_bad_request(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    resp = client.get(
        f"/api/projects/{project['id']}/explorer", params={"path": "main.py"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "not_a_directory"


def test_explorer_file_missing_404(client, sample_project: Path) -> None:
    project = _create(client, sample_project)
    resp = client.get(
        f"/api/projects/{project['id']}/explorer/file",
        params={"path": "nao_existe.py"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "path_not_found"


# ---------------------------------------------------------------------------
# Cancelamento e erros de run
# ---------------------------------------------------------------------------


def test_cancel_pending_then_conflict(
    client, sample_project: Path, make_run, db
) -> None:
    project = _create(client, sample_project)
    row = db.get(Project, project["id"])
    assert row is not None
    rid = make_run(row)

    first = client.post(f"/api/analysis/runs/{rid}/cancel")
    assert first.status_code == 200
    assert first.json()["state"] == "cancelled"

    second = client.post(f"/api/analysis/runs/{rid}/cancel")
    assert second.status_code == 409
    assert second.json()["code"] == "run_finished"


def test_analyze_missing_directory_fails_404(
    client, tmp_path: Path, make_project
) -> None:
    project = make_project(tmp_path / "diretorio_apagado")
    resp = client.post(f"/api/projects/{project.id}/analyze", json={})
    assert resp.status_code == 404
    assert resp.json()["code"] == "project_path_missing"


def test_run_endpoints_404(client) -> None:
    resp = client.get("/api/analysis/runs/9999")
    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"
    assert client.get("/api/graph/9999").status_code == 404
    assert client.get("/api/graph/9999/cycles").status_code == 404
    assert client.get("/api/analysis/runs/9999/files").status_code == 404
    assert client.get("/api/analysis/runs/9999/symbols").status_code == 404
    assert client.get("/api/analysis/runs/9999/dependencies").status_code == 404
    assert client.get("/api/analysis/runs/9999/metrics").status_code == 404


def test_analyze_unknown_project_404(client) -> None:
    resp = client.post("/api/projects/9999/analyze", json={})
    assert resp.status_code == 404
    assert resp.json()["code"] == "project_not_found"


def test_project_run_alias_rejects_foreign_run(
    client, sample_project: Path, tmp_path: Path, make_project, make_run
) -> None:
    project = _create(client, sample_project)
    other_root = tmp_path / "outro_projeto"
    other_root.mkdir()
    foreign_run = make_run(make_project(other_root, name="outro"))

    # list_projects ordena por id.desc(); usar o id criado acima, não [0]
    resp = client.get(f"/api/projects/{project['id']}/analysis/{foreign_run}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"
