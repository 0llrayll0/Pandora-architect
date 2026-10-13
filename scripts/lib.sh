#!/usr/bin/env bash
# Funções comuns dos scripts do Pandora Architect (source, não execute).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
LOG_FILE="$RUN_DIR/backend.log"
PID_FILE="$RUN_DIR/backend.pid"
PORT_FILE="$RUN_DIR/backend.port"

mkdir -p "$RUN_DIR"

log() { printf '[pandora] %s\n' "$*"; }
die() { printf '[pandora] ERRO: %s\n' "$*" >&2; exit 1; }

# Carrega .env da raiz (se existir) e traduz PANDORA_* para as variáveis
# que o backend lê (backend/app/config.py: HOST, PORT, DATA_DIR, ...).
load_env() {
  if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/.env"
    set +a
  fi
  if [ -n "${PANDORA_HOST:-}" ]; then export HOST="$PANDORA_HOST"; fi
  if [ -n "${PANDORA_PORT:-}" ]; then export PORT="$PANDORA_PORT"; fi
  if [ -n "${PANDORA_DATA_DIR:-}" ]; then export DATA_DIR="$PANDORA_DATA_DIR"; fi
  if [ -n "${PANDORA_DB_FILENAME:-}" ]; then export DB_FILENAME="$PANDORA_DB_FILENAME"; fi
  if [ -n "${PANDORA_DEV_ORIGIN:-}" ]; then export DEV_ORIGIN="$PANDORA_DEV_ORIGIN"; fi
  if [ -n "${PANDORA_MAX_FILE_SIZE_BYTES:-}" ]; then export MAX_FILE_SIZE_BYTES="$PANDORA_MAX_FILE_SIZE_BYTES"; fi
  if [ -n "${PANDORA_MAX_FILES:-}" ]; then export MAX_FILES="$PANDORA_MAX_FILES"; fi
  if [ -n "${PANDORA_MAX_DEPTH:-}" ]; then export MAX_DEPTH="$PANDORA_MAX_DEPTH"; fi
}

# Porta efetiva: env var > arquivo do run > 8000.
current_port() {
  if [ -n "${PORT:-}" ]; then
    printf '%s' "$PORT"
  elif [ -f "$PORT_FILE" ]; then
    cat "$PORT_FILE"
  else
    printf '8000'
  fi
}

require_venv() {
  [ -x "$VENV_DIR/bin/python" ] ||
    die "venv não encontrado em backend/.venv — rode scripts/install.sh"
}

# 0 = backend respondendo na porta informada; 1 = livre/offline.
health_ok() {
  local port="$1"
  curl -fsS --max-time 2 "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1
}

# Espera o backend ficar saudável; falha após ~30s.
wait_health() {
  local port="$1" i
  for i in $(seq 1 30); do
    if health_ok "$port"; then return 0; fi
    sleep 1
  done
  return 1
}
