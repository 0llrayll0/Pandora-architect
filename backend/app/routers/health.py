"""Endpoint de saúde da plataforma."""

from __future__ import annotations

import platform
import sys

from fastapi import APIRouter
from sqlmodel import Session, func, select

from ..db import get_engine
from ..models import Project
from ..schemas import HealthOut

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Ping operacional: serviço, banco e contagem de projetos."""
    projects = 0
    database = "ok"
    try:
        with Session(get_engine()) as session:
            projects = session.exec(select(func.count()).select_from(Project)).one()
    except Exception as exc:  # pragma: no cover - banco indisponível
        database = f"error: {type(exc).__name__}"

    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        service="pandora-architect",
        version=VERSION,
        database=database,
        python=platform.python_version(),
        projects=projects,
    )


@router.get("/meta")
def meta() -> dict[str, str]:
    """Metadados mínimos do processo (útil no topo do frontend)."""
    return {
        "service": "pandora-architect",
        "version": VERSION,
        "python": sys.version.split()[0],
        "platform": platform.system(),
    }
