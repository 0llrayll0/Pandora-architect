"""Aplicação FastAPI do Pandora Architect.

- expõe a API sob ``/api``
- em produção serve o build do frontend (``frontend/dist``) se existir
- todos os erros saem no formato ``{"detail": str, "code": str}``
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import init_db
from .errors import ApiException
from .routers import ai, analysis, explorer, graph, health, projects
from .security import SecurityError

API_PREFIX = "/api"
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cria as tabelas na subida e nada mais (leve)."""
    init_db()
    yield


app = FastAPI(
    title="Pandora Architect",
    description="Plataforma local de inteligência sobre repositórios (análise estática).",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()

# CORS restrito: apenas o dev server do Vite em desenvolvimento.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dev_origin, "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Handlers de erro padronizados
# ---------------------------------------------------------------------------


def _error(detail: str, code: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


@app.exception_handler(ApiException)
async def _api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    payload: dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    if exc.extra:
        payload.update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(SecurityError)
async def _security_handler(request: Request, exc: SecurityError) -> JSONResponse:
    return _error(str(exc), exc.code, exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "payload inválido")
    return _error(f"{location}: {message}" if location else str(message), "validation_error", 422)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "erro HTTP"
    code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
    return _error(detail, code, exc.status_code)


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # nunca vaza stacktrace para o cliente
    return _error(f"Erro interno: {type(exc).__name__}", "internal_error", 500)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(analysis.router, prefix=API_PREFIX)
app.include_router(graph.router, prefix=API_PREFIX)
app.include_router(explorer.router, prefix=API_PREFIX)
app.include_router(ai.router, prefix=API_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    info = {
        "service": "pandora-architect",
        "docs": "/docs",
        "api": API_PREFIX,
    }
    if FRONTEND_DIST.exists():
        info["frontend"] = "built"
    else:
        info["frontend"] = "missing (rode scripts/dev.sh ou npm run build)"
    return info


@app.get("/api", include_in_schema=False)
def api_index() -> dict[str, Any]:
    routes = sorted(
        {
            str(route.path)
            for route in app.routes
            if getattr(route, "path", "").startswith(API_PREFIX)
        }
    )
    return {"service": "pandora-architect", "routes": routes}


# ---------------------------------------------------------------------------
# Frontend estático (build) — registrado por último, depois da API
# ---------------------------------------------------------------------------


@app.api_route(
    "/api/{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def api_not_found(rest: str) -> JSONResponse:
    """Qualquer rota /api desconhecida responde JSON 404 (nunca index.html)."""
    return _error(f"Rota não encontrada: /api/{rest}", "not_found", 404)


if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        """Serve o SPA com fallback para index.html (rotas do React)."""
        if full_path.startswith("api/"):
            return _error(f"Rota não encontrada: /{full_path}", "not_found", 404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)  # type: ignore[return-value]
        return FileResponse(FRONTEND_DIST / "index.html")  # type: ignore[return-value]
