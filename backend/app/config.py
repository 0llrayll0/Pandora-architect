"""Configuração central do Pandora Architect (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Configurações operacionais da plataforma.

    Todos os valores podem ser sobrescritos por variáveis de ambiente ou por
    um arquivo ``.env`` na raiz do backend (ver ``.env.example``).
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000

    # Banco de dados
    data_dir: Path = DEFAULT_DATA_DIR
    db_filename: str = "pandora.db"

    # CORS (somente o dev server do Vite em desenvolvimento)
    dev_origin: str = "http://localhost:5173"

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
