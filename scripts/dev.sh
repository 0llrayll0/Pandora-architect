#!/usr/bin/env bash
# Modo desenvolvimento: backend (--reload) + Vite na frente, Ctrl+C para os dois.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_env
require_venv

PORT="$(current_port)"
BACKEND_PORT="$PORT"
command -v ss >/dev/null 2>&1 && { ss -ltn 2>/dev/null | grep -q ":${BACKEND_PORT} " &&
  die "porta ${BACKEND_PORT} ocupada (pare o outro serviço ou use PANDORA_PORT)"; }

cleanup() {
  trap - INT TERM EXIT
  [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
  log "dev encerrado."
}
trap cleanup INT TERM EXIT

log "backend dev em http://127.0.0.1:${PORT} (proxy do Vite: /api)"
(
  cd "$BACKEND_DIR"
  exec "$VENV_DIR/bin/python" -m uvicorn app.main:app \
    --host "${HOST:-127.0.0.1}" --port "$BACKEND_PORT" --reload --log-level info
) &
BACK_PID=$!

log "frontend dev em http://127.0.0.1:5173"
(cd "$FRONTEND_DIR" && npm run dev) &
WEB_PID=$!

wait
