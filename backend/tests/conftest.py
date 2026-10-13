"""Fixtures compartilhadas da suíte de testes do Pandora Architect.

Cada teste roda com:
- SQLite em arquivo temporário (``configure_engine`` + ``init_db``);
- ``PANDORA_ALLOWED_DIRS`` apontando para o ``tmp_path`` (o ``canonicalize``
  rejeita caminhos fora dos diretórios autorizados — sem isso, ``/tmp`` seria
  bloqueado);
- runtime do pipeline zerado (threads + hub de progresso em memória).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.analysis.pipeline import execute_run, reset_runtime
from app.db import configure_engine, get_engine, init_db, reset_engine
from app.main import app
from app.models import AnalysisRun, Project, RunState

# Mini-projeto canônico da suíte: rel_path -> conteúdo.
# Total: 10 arquivos .py elegíveis (main, cycle1, cycle2, broken,
# pkg_a/{__init__,mod,util}, pkg_b/{__init__,service,x}).
SAMPLE_FILES: dict[str, str] = {
    "main.py": (
        '"""Projeto demo do Pandora."""\n'
        "\n"
        "import os\n"
        "\n"
        "import requests\n"
        "\n"
        "from pkg_a import mod\n"
        "from pkg_b import service\n"
        "\n"
        "\n"
        "def main() -> int:\n"
        '    """Executa o demo."""\n'
        '    if os.name == "posix" and True:\n'
        "        for _ in range(1):\n"
        "            mod.run()\n"
        "    return service.run()\n"
    ),
    "cycle1.py": (
        "import cycle2\n"
        "\n"
        "\n"
        "def alpha() -> None:\n"
        "    cycle2.beta()\n"
    ),
    "cycle2.py": (
        "import cycle1\n"
        "\n"
        "\n"
        "def beta() -> None:\n"
        "    cycle1.alpha()\n"
    ),
    "broken.py": "def quebrado(:\n    return 1\n",
    "pkg_a/__init__.py": '"""Pacote A."""\n',
    "pkg_a/mod.py": "def run() -> int:\n    return 1\n",
    "pkg_a/util.py": (
        "from . import mod\n"
        "from .fantasma import helper\n"
        "\n"
        "\n"
        "def usa() -> int:\n"
        "    return mod.run() + helper\n"
    ),
    "pkg_b/__init__.py": '"""Pacote B."""\n',
    "pkg_b/service.py": (
        "from .x import helper\n"
        "\n"
        "\n"
        "def run() -> int:\n"
        "    return helper\n"
    ),
    "pkg_b/x.py": "helper = 42\n",
    # fora dos .py elegíveis (diretórios excluídos por padrão)
    "ignored/node_modules/junk.js": "console.log(1);\n",
    "ignored/.git/x": "nao deve aparecer\n",
}


def write_files(root: Path, files: dict[str, str]) -> None:
    """Cria ``root`` com os arquivos (rel_path -> conteúdo)."""
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isola banco, diretórios autorizados e runtime entre testes."""
    monkeypatch.setenv("PANDORA_ALLOWED_DIRS", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    configure_engine(f"sqlite:///{tmp_path / 'pandora_test.db'}")
    init_db()
    reset_runtime()
    yield tmp_path
    reset_runtime()
    reset_engine()


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Mini-projeto de 10 arquivos .py + exclusões + symlink para fora."""
    root = tmp_path / "proj"
    write_files(root, SAMPLE_FILES)
    # alvo do symlink fica FORA do projeto (mas dentro dos dirs autorizados)
    (tmp_path / "outside_target.py").write_text("alvo externo\n", encoding="utf-8")
    (root / "arquivo.py").symlink_to(Path("..") / "outside_target.py")
    return root


@pytest.fixture
def make_project() -> Callable[..., Project]:
    """Factory: persiste um ``Project`` e devolve a linha."""

    def _make(path: Path, *, name: str = "demo") -> Project:
        with Session(get_engine()) as session:
            project = Project(name=name, path=str(path))
            session.add(project)
            session.commit()
            session.refresh(project)
        return project

    return _make


@pytest.fixture
def make_run() -> Callable[..., int]:
    """Factory: cria uma ``AnalysisRun`` pendente sem disparar thread."""

    def _make(project: Project, *, state: str = RunState.PENDING.value) -> int:
        with Session(get_engine()) as session:
            run = AnalysisRun(project_id=project.id or 0, state=state, stage="queued")
            session.add(run)
            session.commit()
            session.refresh(run)
        return run.id or 0

    return _make


@pytest.fixture
def run_pipeline(make_run) -> Callable[..., int]:
    """Cria a run e executa o pipeline de forma síncrona (sem thread)."""

    def _run(project: Project) -> int:
        run_id = make_run(project)
        execute_run(run_id)
        return run_id

    return _run


@pytest.fixture
def analyzed_project(sample_project: Path, make_project, run_pipeline):
    """Projeto de exemplo já analisado: ``(project, run_id)``."""
    project = make_project(sample_project)
    run_id = run_pipeline(project)
    return project, run_id


@pytest.fixture
def db() -> Iterator[Session]:
    """Sessão SQLModel aberta (fechada no teardown)."""
    session = Session(get_engine())
    yield session
    session.close()


@pytest.fixture
def client(isolated_backend: Path) -> Iterator[TestClient]:
    """TestClient da app (lifespan cria as tabelas no engine já isolado)."""
    with TestClient(app) as test_client:
        yield test_client
