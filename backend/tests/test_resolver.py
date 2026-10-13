"""Testes do resolvedor de imports (confirmed / external / unresolved)."""

from __future__ import annotations

from app.analysis.python_analyzer import ImportRecord
from app.analysis.resolver import (
    EXTERNAL_CONFIDENCE,
    EXTERNAL_UNINSTALLED_CONFIDENCE,
    UNRESOLVED_CONFIDENCE,
    ImportResolver,
    build_module_index,
)

INDEX_PATHS = [
    "broken.py",
    "cycle1.py",
    "cycle2.py",
    "main.py",
    "pkg_a/__init__.py",
    "pkg_a/mod.py",
    "pkg_a/util.py",
    "pkg_b/__init__.py",
    "pkg_b/service.py",
    "pkg_b/x.py",
]


def _resolver() -> ImportResolver:
    return ImportResolver(build_module_index(INDEX_PATHS))


def _abs(module: str, names: list[str] | None = None) -> ImportRecord:
    return ImportRecord(module=module, level=0, names=names or [module.split(".")[0]])


def _rel(module: str, level: int, names: list[str]) -> ImportRecord:
    return ImportRecord(module=module, level=level, names=names)


# ---------------------------------------------------------------------------
# Absolutos
# ---------------------------------------------------------------------------


def test_absolute_submodule_wins_over_package() -> None:
    resolution = _resolver().resolve_absolute(_abs("pkg_a", ["mod"]))
    assert resolution.classification == "confirmed"
    assert resolution.confidence == 1.0
    assert resolution.target_path == "pkg_a/mod.py"
    assert resolution.target_module == "pkg_a.mod"
    assert resolution.note.startswith("submodule:")


def test_absolute_package_fallback() -> None:
    resolution = _resolver().resolve_absolute(_abs("pkg_b", ["pkg_b"]))
    assert resolution.classification == "confirmed"
    assert resolution.target_path == "pkg_b/__init__.py"
    assert resolution.note == "package"


def test_absolute_star_import_resolves_package() -> None:
    record = ImportRecord(module="pkg_a", level=0, names=["*"], is_star=True)
    resolution = _resolver().resolve_absolute(record)
    assert resolution.classification == "confirmed"
    assert resolution.target_path == "pkg_a/__init__.py"


def test_absolute_file_module() -> None:
    resolution = _resolver().resolve_absolute(_abs("cycle2"))
    assert resolution.classification == "confirmed"
    assert resolution.target_path == "cycle2.py"
    assert resolution.note == "module"


def test_absolute_partial_prefix_for_nested_import() -> None:
    # `import pkg_a.mod.extra` → aceita o prefixo mais específico existente
    record = ImportRecord(module="pkg_a.mod.extra", level=0, names=["pkg_a"])
    resolution = _resolver().resolve_absolute(record)
    assert resolution.classification == "confirmed"
    assert resolution.target_module == "pkg_a.mod"
    assert resolution.target_path == "pkg_a/mod.py"
    assert resolution.note == "partial:module"
    assert resolution.confidence == 0.9  # 1.0 - 0.1 * (3 - 2)


def test_absolute_stdlib_is_external() -> None:
    resolution = _resolver().resolve_absolute(_abs("os"))
    assert resolution.classification == "external"
    assert resolution.confidence == EXTERNAL_CONFIDENCE
    assert resolution.confidence == 0.9


def test_absolute_uninstalled_is_external_without_confirmation() -> None:
    # `requests` não está no projeto nem instalado no ambiente do teste
    resolution = _resolver().resolve_absolute(_abs("requests"))
    assert resolution.classification == "external"
    assert resolution.confidence == EXTERNAL_UNINSTALLED_CONFIDENCE
    assert resolution.confidence == 0.5
    assert "fora do projeto" in resolution.note


def test_absolute_empty_module_is_unresolved() -> None:
    resolution = _resolver().resolve_absolute(ImportRecord(module="", level=0, names=[]))
    assert resolution.classification == "unresolved"
    assert resolution.confidence == UNRESOLVED_CONFIDENCE


# ---------------------------------------------------------------------------
# Relativos
# ---------------------------------------------------------------------------


def test_relative_submodule_from_sibling() -> None:
    # em pkg_a/util.py: `from . import mod`
    resolution = _resolver().resolve_relative(_rel("", 1, ["mod"]), "pkg_a.util")
    assert resolution.classification == "confirmed"
    assert resolution.target_module == "pkg_a.mod"
    assert resolution.target_path == "pkg_a/mod.py"
    assert resolution.note == "submodule:module"


def test_relative_from_package_root() -> None:
    # em pkg_a/__init__.py: `from . import mod`
    resolution = _resolver().resolve_relative(_rel("", 1, ["mod"]), "pkg_a")
    assert resolution.classification == "confirmed"
    assert resolution.target_path == "pkg_a/mod.py"


def test_relative_missing_submodule_is_unresolved() -> None:
    # em pkg_a/util.py: `from .fantasma import helper`
    record = _rel("fantasma", 1, ["helper"])
    resolution = _resolver().resolve_relative(record, "pkg_a.util")
    assert resolution.classification == "unresolved"
    assert resolution.confidence == UNRESOLVED_CONFIDENCE
    assert resolution.target_module == "pkg_a.fantasma"


def test_relative_beyond_root_is_unresolved() -> None:
    # módulo de topo não tem pacote pai para subir
    record = _rel("", 1, ["algo"])
    resolution = _resolver().resolve_relative(record, "main")
    assert resolution.classification == "unresolved"
    assert "além da raiz" in resolution.note


def test_relative_level_deeper_than_package_is_unresolved() -> None:
    record = _rel("x", 3, ["y"])
    resolution = _resolver().resolve_relative(record, "pkg_a.util")
    assert resolution.classification == "unresolved"
    assert "além da raiz" in resolution.note


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------


def test_top_level_names() -> None:
    index = build_module_index(INDEX_PATHS)
    assert index.top_level_names() == {
        "broken",
        "cycle1",
        "cycle2",
        "main",
        "pkg_a",
        "pkg_b",
    }


def test_namespace_package_lookup() -> None:
    # diretório sem __init__.py vira namespace
    index = build_module_index(["pkg_c/mod.py"])
    assert index.lookup("pkg_c") == ("pkg_c", "namespace")
    assert index.lookup("pkg_c.mod") == ("pkg_c/mod.py", "module")
    assert "pkg_c" in index.top_level_names()


def test_lookup_unknown_returns_empty() -> None:
    index = build_module_index(INDEX_PATHS)
    assert index.lookup("fantasma") == ("", "")
    assert index.lookup("") == ("", "")
