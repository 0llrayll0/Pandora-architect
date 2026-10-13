"""Testes do walker de descoberta de arquivos (exclusões, limites, leitura)."""

from __future__ import annotations

from pathlib import Path

from app.analysis.discovery import (
    detect_language,
    read_text_limited,
    sha256_of,
    walk_project,
)
from app.config import get_settings
from app.security import DiscoveryLimits, ExclusionRules

from .conftest import write_files


def _rules(**kwargs: object) -> ExclusionRules:
    return ExclusionRules.for_project(get_settings(), **kwargs)  # type: ignore[arg-type]


def _limits(**overrides: int) -> DiscoveryLimits:
    base: dict[str, int] = {
        "max_file_size_bytes": 1024 * 1024,
        "max_files": 5000,
        "max_depth": 30,
    }
    base.update(overrides)
    return DiscoveryLimits(**base)


# ---------------------------------------------------------------------------
# walker no mini-projeto
# ---------------------------------------------------------------------------


def test_walk_finds_only_expected_python_files(sample_project: Path) -> None:
    result = walk_project(sample_project, _rules(), _limits())
    rels = [f.relative_path for f in result.files]

    expected = {
        "main.py",
        "cycle1.py",
        "cycle2.py",
        "broken.py",
        "pkg_a/__init__.py",
        "pkg_a/mod.py",
        "pkg_a/util.py",
        "pkg_b/__init__.py",
        "pkg_b/service.py",
        "pkg_b/x.py",
    }
    assert set(rels) == expected
    assert len(rels) == 10
    assert rels == sorted(rels)  # ordenação estável por caminho
    assert all(f.is_python for f in result.files)
    assert not result.truncated
    assert result.skipped_binary == []
    assert result.skipped_too_large == []


def test_walk_excludes_default_dirs(sample_project: Path) -> None:
    result = walk_project(sample_project, _rules(), _limits())
    rels = [f.relative_path for f in result.files]
    assert not any(r.startswith("ignored/") for r in rels)
    assert not any("node_modules" in r for r in rels)
    assert not any(".git" in r for r in rels)


def test_walk_skips_symlink_pointing_outside(sample_project: Path) -> None:
    result = walk_project(sample_project, _rules(), _limits())
    rels = [f.relative_path for f in result.files]
    assert "arquivo.py" not in rels  # symlink nunca é seguido/aceito aqui


def test_walk_marks_packages(sample_project: Path) -> None:
    result = walk_project(sample_project, _rules(), _limits())
    packages = {f.relative_path for f in result.files if f.is_package}
    assert packages == {"pkg_a/__init__.py", "pkg_b/__init__.py"}


def test_walk_non_directory_returns_empty(tmp_path: Path) -> None:
    file_path = tmp_path / "nao_dir.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    result = walk_project(file_path, _rules(), _limits())
    assert result.files == []
    assert result.total_scanned == 0


# ---------------------------------------------------------------------------
# binários / tamanho / profundidade / limite
# ---------------------------------------------------------------------------


def test_walk_skips_binary_files(tmp_path: Path) -> None:
    root = tmp_path / "bin"
    # .png teria sido excluído antes (default_excluded_globs tem "*.png");
    # .bmp é binário por sufixo e não tem glob — exercita skipped_binary de verdade
    write_files(root, {"ok.py": "x = 1\n", "foto.bmp": "\x89BM\x00\x00"})
    result = walk_project(root, _rules(), _limits())
    assert [f.relative_path for f in result.files] == ["ok.py"]
    assert any(p.endswith("foto.bmp") for p in result.skipped_binary)


def test_walk_skips_files_above_size_limit(tmp_path: Path) -> None:
    root = tmp_path / "big"
    write_files(root, {"pequeno.py": "x=1\n", "grande.py": "y = 1234567890\n"})
    result = walk_project(root, _rules(), _limits(max_file_size_bytes=5))
    assert [f.relative_path for f in result.files] == ["pequeno.py"]
    assert any(p.endswith("grande.py") for p in result.skipped_too_large)


def test_walk_truncates_at_max_files(tmp_path: Path) -> None:
    root = tmp_path / "muitos"
    write_files(root, {f"f{i}.py": f"x = {i}\n" for i in range(5)})
    result = walk_project(root, _rules(), _limits(max_files=2))
    # a travessia PARA no limite (stack.clear + break) — os arquivos restantes
    # não são nem visitados; registra-se apenas o arquivo que estourou o limite
    assert result.truncated is True
    assert len(result.files) == 2
    assert len(result.skipped_limit) >= 1
    assert all(p.endswith(".py") for p in result.skipped_limit)


def test_walk_respects_max_depth(tmp_path: Path) -> None:
    root = tmp_path / "deep"
    write_files(root, {"a/b/c/fundo.py": "x = 1\n", "a/topo.py": "y = 2\n"})

    shallow = walk_project(root, _rules(), _limits(max_depth=2))
    shallow_rels = [f.relative_path for f in shallow.files]
    assert "a/topo.py" in shallow_rels
    assert "a/b/c/fundo.py" not in shallow_rels

    deep = walk_project(root, _rules(), _limits(max_depth=3))
    deep_rels = [f.relative_path for f in deep.files]
    assert "a/b/c/fundo.py" in deep_rels


def test_walk_include_hidden(tmp_path: Path) -> None:
    root = tmp_path / "ocultos"
    write_files(root, {"visivel.py": "x = 1\n", ".escondido.py": "y = 2\n"})

    default = walk_project(root, _rules(), _limits())
    assert [f.relative_path for f in default.files] == ["visivel.py"]

    with_hidden = walk_project(root, _rules(include_hidden=True), _limits())
    assert ".escondido.py" in [f.relative_path for f in with_hidden.files]


def test_walk_extra_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "extra"
    write_files(root, {"ok.py": "x = 1\n", "cache_local/sujo.py": "y = 2\n"})

    default = walk_project(root, _rules(), _limits())
    assert "cache_local/sujo.py" in [f.relative_path for f in default.files]

    custom = walk_project(root, _rules(extra_dirs=["cache_local"]), _limits())
    assert "cache_local/sujo.py" not in [f.relative_path for f in custom.files]


def test_walk_counts_unknown_language_when_allowed(tmp_path: Path) -> None:
    root = tmp_path / "langs"
    write_files(root, {"dados.json": "{}\n", "sem_extensao": "conteudo\n"})
    result = walk_project(root, _rules(), _limits())
    langs = {f.relative_path: f.language for f in result.files}
    assert langs["dados.json"] == "json"
    assert langs["sem_extensao"] == "unknown"
    assert all(not f.is_python for f in result.files)


# ---------------------------------------------------------------------------
# read_text_limited / sha256 / detect_language
# ---------------------------------------------------------------------------


def test_read_text_limited_truncates(tmp_path: Path) -> None:
    target = tmp_path / "grande.txt"
    target.write_text("abcdefghij", encoding="utf-8")
    text, size, truncated = read_text_limited(target, 4)
    assert text == "abcd"
    assert size == 10
    assert truncated is True


def test_read_text_limited_full_file(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text, size, truncated = read_text_limited(target, 100)
    assert text == "x = 1\n"
    assert size == 6
    assert truncated is False


def test_read_text_limited_binary_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "bin.dat"
    target.write_bytes(b"abc\x00def")
    text, _size, _truncated = read_text_limited(target, 100)
    assert text is None


def test_read_text_limited_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "vazio.txt"
    target.write_text("", encoding="utf-8")
    text, size, truncated = read_text_limited(target, 100)
    assert text == ""
    assert size == 0
    assert truncated is False


def test_read_text_limited_missing_file(tmp_path: Path) -> None:
    text, size, truncated = read_text_limited(tmp_path / "nao_existe.py", 100)
    assert text is None
    assert size == 0
    assert truncated is False


def test_sha256_of_is_deterministic() -> None:
    assert sha256_of("abc") == sha256_of("abc")
    assert sha256_of("abc") != sha256_of("abd")
    assert len(sha256_of("abc")) == 64


def test_detect_language() -> None:
    assert detect_language("main.py") == "python"
    assert detect_language("Dockerfile") == "dockerfile"
    assert detect_language("Makefile") == "makefile"
    assert detect_language("estilo.css") == "css"
    assert detect_language("script.sh") == "shell"
    assert detect_language("foto.png") == "binary"
    assert detect_language("arquivo.xyz") == "unknown"
