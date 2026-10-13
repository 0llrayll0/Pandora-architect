"""Resolução de imports Python (absolutos e relativos) dentro do projeto.

Classificação honesta:
- ``confirmed``  → o import aponta para um arquivo/pacote dentro do projeto;
- ``external``   → stdlib ou distribuição instalada no ambiente (não no alvo);
- ``unresolved`` → não foi possível resolver.

Nenhum módulo do repositório analisado é importado: só lemos nomes e
comparamos com o índice de arquivos descobertos.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import lru_cache

from ..models import DependencyClass
from .python_analyzer import ImportRecord

CONFIRMED_CONFIDENCE = 1.0
EXTERNAL_CONFIDENCE = 0.9
# fora do projeto e fora do ambiente: ainda é uma dependência externa, só
# que não temos como confirmar a presença dela (ex.: ``requests`` não instalado)
EXTERNAL_UNINSTALLED_CONFIDENCE = 0.5
UNRESOLVED_CONFIDENCE = 0.0

MODULE_SUFFIXES = (".py", ".pyi")


@dataclass(slots=True)
class Resolution:
    """Resultado da resolução de um único import."""

    classification: str
    confidence: float
    target_module: str = ""
    target_path: str = ""  # relativo à raiz do projeto, quando resolvido
    note: str = ""


@dataclass
class ModuleIndex:
    """Índice módulo dotted -> arquivo (ou diretório de pacote)."""

    modules: dict[str, str] = field(default_factory=dict)  # módulo -> path
    packages: dict[str, str] = field(default_factory=dict)  # __init__ -> path
    namespaces: dict[str, str] = field(default_factory=dict)  # dir sem __init__
    file_to_module: dict[str, str] = field(default_factory=dict)

    def add_file(self, relative_path: str) -> str:
        """Indexa um arquivo Python relativo e devolve o módulo dotted."""
        parts = relative_path.split("/")
        filename = parts[-1]
        dirname = parts[:-1]

        if filename == "__init__.py":
            module = ".".join(dirname)
            self.packages[module] = relative_path
        else:
            stem = filename
            for suffix in MODULE_SUFFIXES:
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            module = ".".join([*dirname, stem]) if dirname else stem
            self.modules[module] = relative_path

        # diretórios intermediários viram pacotes (namespace) se não tiverem __init__
        for depth in range(len(dirname)):
            pkg = ".".join(dirname[: depth + 1])
            self.namespaces.setdefault(pkg, "/".join(dirname[: depth + 1]))
        if filename == "__init__.py":
            self.namespaces[".".join(dirname)] = "/".join(dirname) if dirname else ""

        self.file_to_module[relative_path] = module
        return module

    def lookup(self, dotted: str) -> tuple[str, str]:
        """Procura ``dotted``: pacote com __init__ > módulo > namespace."""
        if not dotted:
            return "", ""
        if dotted in self.modules:
            return self.modules[dotted], "module"
        if dotted in self.packages:
            return self.packages[dotted], "package"
        if dotted in self.namespaces:
            return self.namespaces[dotted], "namespace"
        return "", ""

    def top_level_names(self) -> set[str]:
        """Tops-levels presentes no projeto (para distinguir externo de interno)."""
        tops: set[str] = set()
        for mapping in (self.modules, self.packages, self.namespaces):
            for key in mapping:
                if key:
                    tops.add(key.split(".", 1)[0])
        return tops


@lru_cache(maxsize=1)
def _external_toplevels() -> frozenset[str]:
    """Top-level names de stdlib + distribuições instaladas (só metadados)."""
    names: set[str] = set(getattr(sys, "stdlib_module_names", set()))
    try:
        from importlib.metadata import packages_distributions

        names.update(packages_distributions().keys())
    except Exception:  # pragma: no cover - metadados indisponíveis
        pass
    # nomes locais mais comuns não devem mascarar o projeto
    return frozenset(names)


def _toplevel(name: str) -> str:
    return name.split(".")[0] if name else ""


def classify_external(dotted: str) -> bool:
    """O import corresponde a stdlib ou a pacote instalado no ambiente?"""
    if not dotted:
        return False
    top = _toplevel(dotted)
    known = _external_toplevels()
    if top in known:
        return True
    # `__future__` e afins entram como stdlib; nomes com ponto checados por prefixo
    return dotted in known


class ImportResolver:
    """Resolve ``ImportRecord``s contra o índice do projeto."""

    def __init__(self, index: ModuleIndex) -> None:
        self.index = index

    # -- absolutos ---------------------------------------------------------
    def resolve_absolute(self, record: ImportRecord) -> Resolution:
        dotted = record.module
        if not dotted:
            return Resolution(DependencyClass.UNRESOLVED, UNRESOLVED_CONFIDENCE)

        # `from pkg import mod`: o submódulo é o alvo mais específico.
        for name in record.names:
            if name == "*":
                continue
            candidate = f"{dotted}.{name}"
            path, kind = self.index.lookup(candidate)
            if path:
                return Resolution(
                    DependencyClass.CONFIRMED,
                    CONFIRMED_CONFIDENCE,
                    target_module=candidate,
                    target_path=path,
                    note=f"submodule:{kind}",
                )

        path, kind = self.index.lookup(dotted)
        if path:
            return Resolution(
                DependencyClass.CONFIRMED,
                CONFIRMED_CONFIDENCE,
                target_module=dotted,
                target_path=path,
                note=kind,
            )

        # `import a.b.c` → Python importa a, a.b e a.b.c; aceitar o mais específico
        # que exista (ex.: `import pkg.mod` quando só `pkg` é pacote).
        parts = dotted.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:cut])
            path, kind = self.index.lookup(prefix)
            if path:
                return Resolution(
                    DependencyClass.CONFIRMED,
                    CONFIRMED_CONFIDENCE - 0.1 * (len(parts) - cut),
                    target_module=prefix,
                    target_path=path,
                    note=f"partial:{kind}",
                )

        if classify_external(dotted):
            return Resolution(
                DependencyClass.EXTERNAL,
                EXTERNAL_CONFIDENCE,
                target_module=dotted,
                note="stdlib ou distribuição instalada",
            )

        # Top-level desconhecido do índice do projeto: é uma dependência
        # externa (possivelmente não instalada aqui) — não um import interno.
        top = _toplevel(dotted)
        if top and top not in self.index.top_level_names():
            return Resolution(
                DependencyClass.EXTERNAL,
                EXTERNAL_UNINSTALLED_CONFIDENCE,
                target_module=dotted,
                note="fora do projeto (não resolvido no ambiente)",
            )

        return Resolution(
            DependencyClass.UNRESOLVED,
            UNRESOLVED_CONFIDENCE,
            target_module=dotted,
            note="sem correspondência no projeto nem no ambiente",
        )

    # -- relativos ---------------------------------------------------------
    def resolve_relative(self, record: ImportRecord, current_module: str) -> Resolution:
        base_parts = _package_parts(
            current_module, is_package=current_module in self.index.packages
        )
        if not base_parts and record.level > 0:
            return Resolution(
                DependencyClass.UNRESOLVED,
                UNRESOLVED_CONFIDENCE,
                note="nível relativo além da raiz do pacote",
            )

        steps = record.level - 1
        if steps > len(base_parts):
            return Resolution(
                DependencyClass.UNRESOLVED,
                UNRESOLVED_CONFIDENCE,
                note="nível relativo além da raiz do pacote",
            )
        base = base_parts[: len(base_parts) - steps] if steps else base_parts

        suffix = [p for p in (record.module or "").split(".") if p]
        target = ".".join([*base, *suffix])

        # `from . import x` / `from ..pkg_a import mod`: submódulo primeiro
        for name in record.names:
            if name == "*":
                continue
            candidate = f"{target}.{name}" if target else name
            path, kind = self.index.lookup(candidate)
            if path:
                return Resolution(
                    DependencyClass.CONFIRMED,
                    CONFIRMED_CONFIDENCE,
                    target_module=candidate,
                    target_path=path,
                    note=f"submodule:{kind}",
                )

        path, kind = self.index.lookup(target) if target else ("", "")
        if path:
            return Resolution(
                DependencyClass.CONFIRMED,
                CONFIRMED_CONFIDENCE,
                target_module=target,
                target_path=path,
                note=kind,
            )

        if not record.module and not record.names:
            return Resolution(
                DependencyClass.UNRESOLVED, UNRESOLVED_CONFIDENCE, note="import vazio"
            )

        return Resolution(
            DependencyClass.UNRESOLVED,
            UNRESOLVED_CONFIDENCE,
            target_module=target,
            note="relativo não resolvido dentro do projeto",
        )


def _package_parts(module: str, *, is_package: bool) -> list[str]:
    """Partes do pacote que contém ``module`` (base dos imports relativos)."""
    if not module:
        return []
    parts = [p for p in module.split(".") if p]
    if is_package:
        return parts
    return parts[:-1]


def build_module_index(relative_paths: list[str]) -> ModuleIndex:
    """Constrói o índice de módulos a partir dos caminhos Python relativos."""
    index = ModuleIndex()
    for rel in sorted(relative_paths):
        index.add_file(rel)
    return index
