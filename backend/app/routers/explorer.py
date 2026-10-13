"""Explorador de arquivos do projeto ativo (somente leitura, sem execução)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..errors import bad_request, not_found
from ..models import FileMeta, Symbol
from ..security import ExclusionRules, safe_join
from .common import get_project_or_404

router = APIRouter(prefix="/projects", tags=["explorer"])

MAX_PREVIEW_BYTES = 200 * 1024  # 200 KB por pré-visualização
MAX_DEPTH = 6


def _root_for(session: Session, project_id: int) -> Any:
    project = get_project_or_404(session, project_id)
    root = Path(project.path)
    if not root.is_dir():
        raise not_found(
            f"O diretório do projeto não existe mais: {root}",
            code="project_path_missing",
        )
    return project, root


@router.get("/{project_id}/explorer")
def explorer_tree(
    project_id: int,
    path: str = Query(default="", description="Subcaminho relativo à raiz"),
    depth: int = Query(default=1, ge=1, le=MAX_DEPTH),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Lista um diretório do projeto (respeta exclusões padrão)."""
    project, root = _root_for(session, project_id)
    settings = get_settings()
    rules = ExclusionRules.for_project(
        settings,
        extra_dirs=project.extra_excluded_dirs,
        extra_globs=project.extra_excluded_globs,
        include_hidden=project.include_hidden,
    )
    current = safe_join(root, path)

    if not current.exists():
        raise not_found(f"Caminho não encontrado: {path}", code="path_not_found")
    if not current.is_dir():
        raise bad_request(f"O caminho não é um diretório: {path}", code="not_a_directory")

    # caminhos já conhecidos do último snapshot (para mostrar o que foi analisado)
    analyzed = set(
        session.exec(select_file_paths_latest(session, project_id)).all()
    )

    entries: list[dict[str, Any]] = []

    def walk(directory: Path, rel: str, level: int) -> None:
        if level > depth:
            return
        try:
            with os.scandir(directory) as scanner:
                children = sorted(scanner, key=lambda e: (not e.is_dir(), e.name.lower()))
        except (PermissionError, FileNotFoundError, NotADirectoryError):
            return
        for entry in children:
            name = entry.name
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and rules.is_excluded_dir(name):
                continue
            if not is_dir and rules.is_excluded_file(name):
                continue
            child_rel = f"{rel}/{name}" if rel else name
            item: dict[str, Any] = {
                "name": name,
                "path": child_rel,
                "type": "dir" if is_dir else "file",
                "analyzed": child_rel in analyzed,
            }
            if not is_dir:
                try:
                    item["size_bytes"] = entry.stat(follow_symlinks=False).st_size
                except OSError:  # pragma: no cover
                    item["size_bytes"] = 0
            entries.append(item)
            if is_dir and level < depth:
                walk(Path(entry.path), child_rel, level + 1)

    walk(current, path.strip("/"), 1)
    return {
        "path": path.strip("/"),
        "root": str(root),
        "entries": entries,
        "analyzed_paths": len(analyzed),
    }


@router.get("/{project_id}/explorer/file")
def explorer_file(
    project_id: int,
    path: str = Query(..., description="Caminho relativo à raiz do projeto"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Conteúdo de um arquivo (limitado) + símbolos extraídos, se analisado."""
    _project, root = _root_for(session, project_id)
    if not path:
        raise bad_request("Informe o caminho do arquivo.", code="invalid_path")
    target = safe_join(root, path)

    if not target.exists() or not target.is_file():
        raise not_found(f"Arquivo não encontrado: {path}", code="path_not_found")

    try:
        size = target.stat().st_size
    except OSError as exc:  # pragma: no cover
        raise not_found(f"Arquivo ilegível: {path}", code="path_not_found") from exc

    raw = b""
    truncated = False
    if size <= MAX_PREVIEW_BYTES:
        try:
            raw = target.read_bytes()
        except OSError as exc:  # pragma: no cover
            raise not_found(f"Arquivo ilegível: {path}", code="path_not_found") from exc
    else:
        truncated = True
        try:
            with target.open("rb") as handle:
                raw = handle.read(MAX_PREVIEW_BYTES)
        except OSError as exc:  # pragma: no cover
            raise not_found(f"Arquivo ilegível: {path}", code="path_not_found") from exc

    if b"\x00" in raw[:8192]:
        raise bad_request("Arquivo binário não pode ser exibido.", code="binary_file")

    text = raw.decode("utf-8", errors="replace")

    meta = session.exec(
        select_latest_file(session, project_id, path)
    ).first()
    symbols: list[dict[str, Any]] = []
    if meta is not None and meta.id is not None:
        rows = session.exec(
            select_symbols_for_file(session, meta.run_id, meta.id)
        ).all()
        symbols = [
            {
                "name": row.name,
                "kind": row.kind,
                "qualified_name": row.qualified_name,
                "lineno": row.lineno,
                "complexity": row.complexity,
            }
            for row in rows
        ]

    return {
        "path": path,
        "size_bytes": size,
        "truncated": truncated,
        "language": meta.language if meta else "unknown",
        "parse_ok": meta.parse_ok if meta else None,
        "parse_error": meta.parse_error if meta else "",
        "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "content": text,
        "symbols": symbols,
    }


def select_file_paths_latest(session: Session, project_id: int) -> Any:
    """Seleção dos caminhos da análise mais recente concluída do projeto."""
    from sqlmodel import select

    from ..models import AnalysisRun

    sub = (
        select(AnalysisRun.id)
        .where(
            AnalysisRun.project_id == project_id,
            AnalysisRun.state == "completed",
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    ).scalar_subquery()
    return select(FileMeta.path).where(FileMeta.run_id == sub)


def select_latest_file(session: Session, project_id: int, rel_path: str) -> Any:
    """FileMeta do arquivo na análise mais recente concluída."""
    from sqlmodel import select

    from ..models import AnalysisRun

    sub = (
        select(AnalysisRun.id)
        .where(
            AnalysisRun.project_id == project_id,
            AnalysisRun.state == "completed",
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    ).scalar_subquery()
    return select(FileMeta).where(FileMeta.run_id == sub, FileMeta.path == rel_path)


def select_symbols_for_file(session: Session, run_id: int, file_id: int) -> Any:
    from sqlmodel import select

    return select(Symbol).where(Symbol.run_id == run_id, Symbol.file_id == file_id)
