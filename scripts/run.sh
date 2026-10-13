#!/usr/bin/env bash
# Sobe o backend (FastAPI) em background servindo também o build do frontend.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

load_env
require_venv

PORT="$(current_port)"
HOST="${HOST:-127.0.0.1}"

if health_ok "$PORT"; then
  log "backend já está no ar em http://127.0.0.1:${PORT}"
  exit 0
fi

# Porta ocupada por outro processo que não responde /api/health → não roubar.
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  die "porta ${PORT} ocupada por outro processo (use PANDORA_PORT para mudar)"
fi

# Build do frontend (a API serve frontend/dist quando existe).
if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
  log "frontend/dist ausente — rodando build"
  (cd "$FRONTEND_DIR" && npm run build)
fi

log "subindo backend em http://127.0.0.1:${PORT} (log: ${LOG_FILE#"$ROOT/"})"
(
  cd "$BACKEND_DIR"
  exec "$VENV_DIR/bin/python" -m uvicorn app.main:app \
    --host "$HOST" --port "$PORT" --log-level info
) >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
printf '%s' "$PORT" >"$PORT_FILE"

if wait_health "$PORT"; then
  log "ok → http://127.0.0.1:${PORT}"
  log "UI: http://127.0.0.1:${PORT}/index.html (a raiz / é JSON de status; API: /api/health)"
else
  tail -n 20 "$LOG_FILE" >&2 || true
  die "backend não respondeu em 30s — veja ${LOG_FILE#"$ROOT/"}"
fi
