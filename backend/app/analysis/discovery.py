"""Descoberta de arquivos (walker) com exclusões, limites e symlinks seguros."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..security import (
    DiscoveryLimits,
    ExclusionRules,
    SecurityError,
    ensure_within_root,
)

# Extensão -> linguagem (apenas para classificação; nenhum código é executado).
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".rst": "rst",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".ini": "ini",
    ".cfg": "ini",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sh": "shell",
    ".bash": "shell",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".sql": "sql",
    ".graphql": "graphql",
    ".proto": "protobuf",
    ".txt": "text",
    ".dockerfile": "dockerfile",
}

TEXT_SUFFIXES = set(LANGUAGE_BY_SUFFIX) | {".env", ".example", ".in", ".lock"}

# Extensões binárias nunca lidas.
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".pdf",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a", ".class", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".avi",
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".pyd",
}


@dataclass(slots=True)
class DiscoveredFile:
    """Arquivo aceito pela descoberta."""

    absolute_path: Path
    relative_path: str
    size_bytes: int
    language: str
    is_python: bool
    is_package: bool = False


@dataclass
class DiscoveryResult:
    """Resultado de uma varredura completa."""

    files: list[DiscoveredFile] = field(default_factory=list)
    skipped_too_large: list[str] = field(default_factory=list)
    skipped_binary: list[str] = field(default_factory=list)
    skipped_limit: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def total_scanned(self) -> int:
        return len(self.files) + len(self.skipped_too_large) + len(self.skipped_binary)


def detect_language(name: str) -> str:
    """Classifica a linguagem pelo nome/sufixo do arquivo."""
    lower = name.lower()
    if lower == "dockerfile":
        return "dockerfile"
    if lower == "makefile":
        return "makefile"
    suffix = Path(lower).suffix
    if suffix in LANGUAGE_BY_SUFFIX:
        return LANGUAGE_BY_SUFFIX[suffix]
    if suffix in BINARY_SUFFIXES:
        return "binary"
    return "unknown"


def _is_probably_binary(sample: bytes) -> bool:
    """Heurística simples: bytes nulos no começo do arquivo indicam binário."""
    return b"\x00" in sample


def read_text_limited(path: Path, max_bytes: int) -> tuple[str | None, int, bool]:
    """Lê até ``max_bytes`` bytes decodificando como UTF-8 (fallback latin-1).

    Retorna ``(conteúdo | None, tamanho, truncated)``. Conteúdo ``None`` quando
    o arquivo se comporta como binário.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None, 0, False

    if size == 0:
        return "", 0, False

    try:
        with path.open("rb") as fh:
            raw = fh.read(max_bytes + 1)
    except OSError:
        return None, size, False

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]

    if _is_probably_binary(raw[:8192]):
        return None, size, truncated

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError:  # pragma: no cover
            return None, size, truncated
    return text, size, truncated


def sha256_of(text: str) -> str:
    """Hash do conteúdo lido (para rastreabilidade do snapshot)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def walk_project(
    root: Path,
    rules: ExclusionRules,
    limits: DiscoveryLimits,
    *,
    include_unknown: bool = True,
) -> DiscoveryResult:
    """Percorre ``root`` aplicando exclusões, profundidade e limite de arquivos.

    - Não segue symlink que saia da raiz (``ensure_within_root``).
    - Ignora diretórios/arquivos pelas regras padrão + exceções do projeto.
    - Para no ``max_files`` e sinaliza ``truncated=True``.
    """
    result = DiscoveryResult()
    root_resolved = root.resolve()
    if not root_resolved.is_dir():
        return result

    # (caminho absoluto, profundidade)
    stack: list[tuple[Path, int]] = [(root_resolved, 0)]
    visited_dirs: set[str] = set()

    while stack:
        current, depth = stack.pop()

        try:
            with os.scandir(current) as scanner:
                entries = sorted(scanner, key=lambda e: e.name)
        except (PermissionError, FileNotFoundError, NotADirectoryError):
            continue

        for entry in entries:
            name = entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:  # pragma: no cover
                continue

            if is_dir:
                if rules.is_excluded_dir(name):
                    continue
                if depth + 1 > limits.max_depth:
                    continue

                # symlink de diretório: só seguir se o alvo continuar na raiz
                if entry.is_symlink() and not rules_ok_as_symlink(
                    entry.path, root_resolved
                ):
                    continue
                child = Path(entry.path)
                try:
                    child_resolved = child.resolve()
                except (OSError, RuntimeError):  # pragma: no cover
                    continue
                if child_resolved in visited_dirs:
                    continue
                if not _within(child_resolved, root_resolved):
                    continue
                visited_dirs.add(child_resolved)
                stack.append((child_resolved, depth + 1))
                continue

            if not entry.is_file(follow_symlinks=False):
                continue
            if rules.is_excluded_file(name):
                continue

            file_path = Path(entry.path)
            if file_path.is_symlink() and not _within(
                _safe_resolve(file_path), root_resolved
            ):
                continue

            try:
                file_size = entry.stat(follow_symlinks=False).st_size
            except OSError:  # pragma: no cover
                continue

            language = detect_language(name)
            if language == "binary":
                result.skipped_binary.append(str(file_path))
                continue
            if language == "unknown" and not include_unknown:
                result.skipped_binary.append(str(file_path))
                continue
            if file_size > limits.max_file_size_bytes:
                result.skipped_too_large.append(str(file_path))
                continue

            if len(result.files) >= limits.max_files:
                result.truncated = True
                result.skipped_limit.append(str(file_path))
                stack.clear()
                break

            relative = file_path.relative_to(root_resolved).as_posix()
            result.files.append(
                DiscoveredFile(
                    absolute_path=file_path,
                    relative_path=relative,
                    size_bytes=file_size,
                    language=language,
                    is_python=language == "python",
                    is_package=name == "__init__.py",
                )
            )

    result.files.sort(key=lambda f: f.relative_path)
    return result


def rules_ok_as_symlink(path: str, root: Path) -> bool:
    """Symlink de diretório só é aceito se o alvo continuar sob a raiz."""
    return _within(_safe_resolve(Path(path)), root)


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):  # pragma: no cover
        return path


def _within(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except (OSError, ValueError):  # pragma: no cover
        return False


def assert_inside(root: Path, path: Path) -> Path:
    """Wrapper explícito para validação de um caminho dentro da raiz."""
    return ensure_within_root(path, root)


__all__ = [
    "BINARY_SUFFIXES",
    "DiscoveredFile",
    "DiscoveryResult",
    "ExclusionRules",
    "SecurityError",
    "detect_language",
    "read_text_limited",
    "sha256_of",
    "walk_project",
]
