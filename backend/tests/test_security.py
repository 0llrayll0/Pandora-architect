"""Testes de segurança de caminhos, exclusões e limites."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.security import (
    DiscoveryLimits,
    ExclusionRules,
    SecurityError,
    authorized_roots,
    canonicalize,
    ensure_within_root,
    safe_join,
    validate_size,
)

# ---------------------------------------------------------------------------
# canonicalize
# ---------------------------------------------------------------------------


def test_canonicalize_rejects_empty_path() -> None:
    with pytest.raises(SecurityError) as exc:
        canonicalize("")
    assert exc.value.code == "invalid_path"
    assert exc.value.status_code == 403


def test_canonicalize_rejects_blank_path() -> None:
    with pytest.raises(SecurityError) as exc:
        canonicalize("   ")
    assert exc.value.code == "invalid_path"


def test_canonicalize_rejects_outside_allowed_dirs() -> None:
    with pytest.raises(SecurityError) as exc:
        canonicalize("/etc")
    assert exc.value.code == "path_not_allowed"
    assert exc.value.status_code == 403


def test_canonicalize_accepts_allowed_dir(tmp_path: Path) -> None:
    resolved = canonicalize(str(tmp_path))
    assert resolved == tmp_path.resolve()


def test_canonicalize_resolves_relative_path_under_allowed_cwd(tmp_path: Path) -> None:
    # o teste roda com cwd == tmp_path (fixture isolada)
    resolved = canonicalize("subdir")
    assert resolved == (tmp_path / "subdir").resolve()


def test_canonicalize_requires_existence(tmp_path: Path) -> None:
    with pytest.raises(SecurityError) as exc:
        canonicalize(str(tmp_path / "fantasma"), must_exist=True)
    assert exc.value.code == "path_not_found"


def test_canonicalize_requires_directory(tmp_path: Path) -> None:
    target = tmp_path / "arquivo.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(SecurityError) as exc:
        canonicalize(str(target), must_exist=True, must_be_dir=True)
    assert exc.value.code == "not_a_directory"


def test_canonicalize_traversal_is_contained(tmp_path: Path) -> None:
    # travessia ainda termina sob a raiz autorizada (resolve canônico)
    resolved = canonicalize(str(tmp_path / "a" / ".." / "b"))
    assert resolved == (tmp_path / "b").resolve()
    # caminho absoluto fora dos roots é bloqueado mesmo que exista
    with pytest.raises(SecurityError):
        canonicalize("/proc/sys/kernel/hostname")


# ---------------------------------------------------------------------------
# authorized_roots
# ---------------------------------------------------------------------------


def test_authorized_roots_includes_env_dirs(tmp_path: Path) -> None:
    roots = authorized_roots()
    assert tmp_path.resolve() in [r.resolve() for r in roots]


# ---------------------------------------------------------------------------
# safe_join / ensure_within_root
# ---------------------------------------------------------------------------


def test_safe_join_simple(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert safe_join(root, "sub/arquivo.py") == (root.resolve() / "sub" / "arquivo.py")


def test_safe_join_dot_returns_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert safe_join(root, ".") == root.resolve()
    assert safe_join(root, "") == root.resolve()


def test_safe_join_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SecurityError) as exc:
        safe_join(root, "../../etc/passwd")
    assert exc.value.code == "path_not_allowed"


def test_safe_join_blocks_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SecurityError):
        safe_join(root, "/etc/passwd")


def test_safe_join_blocks_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("segredo", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(Path("..") / "secret.txt")
    with pytest.raises(SecurityError) as exc:
        safe_join(root, "link.txt")
    assert exc.value.code == "path_not_allowed"


def test_safe_join_allows_inner_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.py").write_text("x = 1\n", encoding="utf-8")
    (root / "alias.py").symlink_to(Path("real.py"))
    assert safe_join(root, "alias.py") == (root.resolve() / "real.py")


def test_ensure_within_root_blocks_outside(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SecurityError):
        ensure_within_root(tmp_path.resolve(), root.resolve())
    assert ensure_within_root(root.resolve(), root.resolve()) == root.resolve()


# ---------------------------------------------------------------------------
# validate_size
# ---------------------------------------------------------------------------


def test_validate_size_rejects_oversized_file(tmp_path: Path) -> None:
    limits = DiscoveryLimits(max_file_size_bytes=10, max_files=100, max_depth=5)
    validate_size(10, limits, "ok.py")
    with pytest.raises(SecurityError) as exc:
        validate_size(11, limits, "grande.py")
    assert exc.value.code == "limit_exceeded"


# ---------------------------------------------------------------------------
# ExclusionRules
# ---------------------------------------------------------------------------


def test_exclusion_rules_defaults() -> None:
    rules = ExclusionRules.for_project(get_settings())
    assert rules.is_excluded_dir("node_modules")
    assert rules.is_excluded_dir(".git")
    assert rules.is_excluded_dir("__pycache__")
    assert rules.is_excluded_dir("venv")
    assert rules.is_excluded_dir("qualquer_oculta") is False  # sem ponto
    assert rules.is_excluded_dir(".qualquer")  # ocultas bloqueadas por padrão
    assert rules.is_excluded_file("bundle.min.js")
    assert rules.is_excluded_file("lib.map")
    assert rules.is_excluded_file("frota.png")
    assert rules.is_excluded_file(".env")  # arquivos ocultos bloqueados por padrão
    assert not rules.is_excluded_file("main.py")
    assert not rules.is_excluded_dir("src")


def test_exclusion_rules_include_hidden() -> None:
    rules = ExclusionRules.for_project(get_settings(), include_hidden=True)
    assert not rules.is_excluded_dir(".github")
    assert not rules.is_excluded_file(".env")
    # mesmo com hidden liberado, padrões glob continuam valendo
    assert rules.is_excluded_dir("node_modules")


def test_exclusion_rules_project_overrides() -> None:
    rules = ExclusionRules.for_project(
        get_settings(),
        extra_dirs=["cache_local"],
        extra_globs=["*.tmp"],
    )
    assert rules.is_excluded_dir("cache_local")
    assert rules.is_excluded_file("notas.tmp")
    assert not rules.is_excluded_dir("outro")


# ---------------------------------------------------------------------------
# DiscoveryLimits
# ---------------------------------------------------------------------------


def test_discovery_limits_from_settings() -> None:
    settings = get_settings()
    limits = DiscoveryLimits.from_settings(settings)
    assert limits.max_file_size_bytes == settings.max_file_size_bytes
    assert limits.max_files == settings.max_files
    assert limits.max_depth == settings.max_depth
