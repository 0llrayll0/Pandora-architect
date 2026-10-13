"""Segurança de caminhos e limites operacionais.

Regras:
- Todo caminho enviado pelo cliente é canonicalizado (``Path.resolve()``)
  e precisa permanecer sob um diretório autorizado (home do usuário ou
  ``PANDORA_ALLOWED_DIRS``). Qualquer fuga → ``SecurityError`` (HTTP 403).
- Symlinks não são seguidos para fora da raiz do projeto analisado.
- Repositórios analisados são tratados como **não confiáveis**: nunca são
  importados nem executados pelo Pandora Architect.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings, get_settings

# Erro de domínio traduzido pelo handler global da API em {"detail","code"}.
SECURITY_ERROR_CODE = "path_not_allowed"
LIMIT_ERROR_CODE = "limit_exceeded"


class SecurityError(Exception):
    """Violação de política de caminhos (HTTP 403)."""

    def __init__(self, message: str, code: str = SECURITY_ERROR_CODE) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = 403


@dataclass(frozen=True)
class DiscoveryLimits:
    """Limites de descoberta de arquivos (configuráveis)."""

    max_file_size_bytes: int
    max_files: int
    max_depth: int

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> DiscoveryLimits:
        s = settings or get_settings()
        return cls(
            max_file_size_bytes=s.max_file_size_bytes,
            max_files=s.max_files,
            max_depth=s.max_depth,
        )


@dataclass
class ExclusionRules:
    """Regras de exclusão combinando padrão + exceções do projeto."""

    excluded_dirs: tuple[str, ...] = ()
    excluded_globs: tuple[str, ...] = ()
    extra_excluded_dirs: tuple[str, ...] = field(default_factory=tuple)
    extra_excluded_globs: tuple[str, ...] = field(default_factory=tuple)
    include_hidden: bool = False

    @classmethod
    def for_project(
        cls,
        settings: Settings,
        extra_dirs: list[str] | None = None,
        extra_globs: list[str] | None = None,
        include_hidden: bool = False,
    ) -> ExclusionRules:
        """Regras = padrões globais da instalação + exceções do projeto."""
        return cls(
            excluded_dirs=tuple(settings.default_excluded_dirs),
            excluded_globs=tuple(settings.default_excluded_globs),
            extra_excluded_dirs=tuple(extra_dirs or ()),
            extra_excluded_globs=tuple(extra_globs or ()),
            include_hidden=include_hidden,
        )

    def is_excluded_dir(self, name: str) -> bool:
        """Nome de diretório bloqueado pelo padrão, pelo *.glob ou pelo projeto."""
        patterns = (
            self.excluded_dirs
            + self.extra_excluded_dirs
            + self.excluded_globs
            + self.extra_excluded_globs
        )
        if not self.include_hidden and name.startswith(".") and name not in (".", ".."):
            # diretórios ocultos são ignorados por padrão
            return True
        return any(fnmatch.fnmatch(name, p) for p in patterns)

    def is_excluded_file(self, name: str) -> bool:
        """Nome de arquivo bloqueado (binários, minificados, caches...)."""
        patterns = self.excluded_globs + self.extra_excluded_globs
        if not self.include_hidden and name.startswith("."):
            return True
        return any(fnmatch.fnmatch(name, p) for p in patterns)


def authorized_roots(settings: Settings | None = None) -> list[Path]:
    """Diretórios sob os quais caminhos de entrada são aceitos."""
    s = settings or get_settings()
    roots: list[Path] = []
    with contextlib.suppress(OSError, RuntimeError):  # pragma: no cover - home quase sempre existe
        roots.append(Path.home().resolve())
    roots.append(Path.cwd().resolve())
    raw = os.environ.get("PANDORA_ALLOWED_DIRS", "")
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).expanduser().resolve())
    # a raiz de dados (onde fica o .db) também é autorizada por coerência
    with contextlib.suppress(OSError):  # pragma: no cover
        roots.append(s.data_dir.resolve())
    return roots


def canonicalize(
    raw_path: str,
    *,
    settings: Settings | None = None,
    must_exist: bool = False,
    must_be_dir: bool = False,
) -> Path:
    """Canonica um caminho vindo do cliente e valida política de acesso.

    Levanta ``SecurityError`` (403) para travessia de path, caminho vazio,
    arquivo inexistente (quando exigido) ou saída dos diretórios autorizados.
    """
    if not raw_path or not str(raw_path).strip():
        raise SecurityError("Caminho vazio.", code="invalid_path")

    candidate = Path(str(raw_path)).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # pragma: no cover -symlink loop
        raise SecurityError(f"Caminho inválido: {exc}", code="invalid_path") from exc

    roots = authorized_roots(settings)
    if not any(_is_within(resolved, root) for root in roots):
        raise SecurityError(
            f"Caminho fora dos diretórios autorizados: {resolved}",
            code=SECURITY_ERROR_CODE,
        )

    if must_exist and not resolved.exists():
        raise SecurityError(f"Caminho não existe: {resolved}", code="path_not_found")

    if must_be_dir and resolved.exists() and not resolved.is_dir():
        raise SecurityError(
            f"Caminho não é um diretório: {resolved}", code="not_a_directory"
        )

    return resolved


def _is_within(path: Path, root: Path) -> bool:
    """``path`` está sob ``root`` (comparação canônica)."""
    try:
        return path == root or path.is_relative_to(root)
    except (OSError, ValueError):  # pragma: no cover
        return False


def ensure_within_root(path: Path, root: Path) -> Path:
    """Garante que ``path`` (já resolvido) permanece sob ``root``."""
    if not _is_within(path, root):
        raise SecurityError(
            f"Acesso negado: {path} está fora da raiz {root}", code=SECURITY_ERROR_CODE
        )
    return path


def safe_join(root: Path, relative: str) -> Path:
    """Junta um caminho relativo à raiz validando contra traversal.

    O resultado é resolvido (symlinks incluídos) e precisa continuar dentro
    da raiz — ``../../etc/passwd`` ou symlink apontando para fora → 403.
    """
    if not relative or relative.strip() in {".", "./"}:
        return ensure_within_root(root.resolve(), root.resolve())

    rel = Path(relative)
    if rel.is_absolute():
        raise SecurityError(
            "Caminho absoluto não é permitido aqui.", code=SECURITY_ERROR_CODE
        )

    joined = root / rel
    try:
        resolved = joined.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # pragma: no cover
        raise SecurityError(f"Caminho inválido: {exc}") from exc

    root_resolved = root.resolve()
    if not _is_within(resolved, root_resolved):
        raise SecurityError(
            "Travessia de caminho detectada.", code=SECURITY_ERROR_CODE
        )
    # se o caminho existir e for symlink saindo da raiz, rejeitar
    if joined.is_symlink():
        ensure_within_root(resolved, root_resolved)
    return resolved


def validate_size(size: int, limits: DiscoveryLimits, path: str) -> None:
    """Rejeita arquivos acima do limite configurado."""
    if size > limits.max_file_size_bytes:
        raise SecurityError(
            f"Arquivo maior que o limite ({limits.max_file_size_bytes} bytes): {path}",
            code=LIMIT_ERROR_CODE,
        )
