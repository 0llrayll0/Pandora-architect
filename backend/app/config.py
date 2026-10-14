"""Configuração central do Pandora Architect (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"

#: Provedores de IA aceitos pelo campo ``ai_provider`` (config e endpoints).
AI_PROVIDERS: tuple[str, ...] = (
    "ollama",
    "openai",
    "custom",
    "anthropic",
    "gemini",
)


class Settings(BaseSettings):
    """Configurações operacionais da plataforma.

    Todos os valores podem ser sobrescritos por variáveis de ambiente ou por
    um arquivo ``.env`` na raiz do backend (ver ``.env.example``).
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000

    # Banco de dados
    data_dir: Path = DEFAULT_DATA_DIR
    db_filename: str = "pandora.db"

    # CORS (somente o dev server do Vite em desenvolvimento)
    dev_origin: str = "http://localhost:5173"

    # Arquiteto IA (Fase 6) — Ollama local é OPCIONAL: se indisponível o
    # relatório sai só com heurísticas determinísticas (nunca 500).
    ollama_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("PANDORA_OLLAMA_URL", "ollama_url"),
    )
    ollama_model: str = Field(
        default="qwen2.5-coder:latest",
        validation_alias=AliasChoices("PANDORA_OLLAMA_MODEL", "ollama_model"),
    )

    # Provedor de IA: "ollama" (local), "openai", "custom", "anthropic" ou
    # "gemini". Os valores persistidos na tabela ``settings`` têm prioridade
    # sobre estas vars de ambiente (ver ``routers/ai.py::_resolve_ai_config``).
    # ``ai_api_key`` NUNCA é devolvida por endpoint GET nem logada.
    ai_provider: str = Field(
        default="ollama",
        validation_alias=AliasChoices("PANDORA_AI_PROVIDER", "ai_provider"),
    )
    ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PANDORA_AI_API_KEY", "ai_api_key"),
    )
    ai_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("PANDORA_AI_BASE_URL", "ai_base_url"),
    )
    ai_model: str = Field(
        default="",
        validation_alias=AliasChoices("PANDORA_AI_MODEL", "ai_model"),
    )

    @field_validator("ai_provider", mode="before")
    @classmethod
    def _validate_ai_provider(cls, value: Any) -> str:
        """Provedor desconhecido (env/``.env``) cai em ``ollama``."""
        provider = str(value or "ollama").strip().lower()
        return provider if provider in AI_PROVIDERS else "ollama"

    # Limites de descoberta de arquivos
    max_file_size_bytes: int = 1024 * 1024  # 1 MB
    max_files: int = 5000
    max_depth: int = 30

    # Exclusões padrão (diretórios e padrões de nome de arquivo)
    default_excluded_dirs: tuple[str, ...] = (
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "dist",
        "build",
        "coverage",
        ".next",
        ".nuxt",
        ".cache",
        "target",
        "vendor",
        "eggs",
        ".eggs",
        "*.egg-info",
        ".idea",
        ".vscode",
    )
    default_excluded_globs: tuple[str, ...] = (
        "*.min.js",
        "*.min.css",
        "*.min.map",
        "*.map",
        "*.pyc",
        "*.pyo",
        "*.so",
        "*.dll",
        "*.dylib",
        "*.exe",
        "*.bin",
        "*.lock",
        "*.sqlite3",
        "*.db",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.gif",
        "*.ico",
        "*.svg",
        "*.woff",
        "*.woff2",
        "*.ttf",
        "*.eot",
        "*.mp4",
        "*.zip",
        "*.tar",
        "*.gz",
        "*.tgz",
        "*.jar",
        "*.class",
        "*.whl",
    )

    @property
    def db_path(self) -> Path:
        """Caminho absoluto do arquivo SQLite."""
        return self.data_dir / self.db_filename


def get_settings() -> Settings:
    """Instância única (lazy) das configurações."""
    return Settings()
