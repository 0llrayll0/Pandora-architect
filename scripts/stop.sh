#!/usr/bin/env bash
# Para o backend iniciado por scripts/run.sh.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ ! -f "$PID_FILE" ]; then
  log "nenhum pidfile em ${PID_FILE#"$ROOT/"} — nada a parar"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  log "processo $PID não está mais rodando — limpando pidfile"
  rm -f "$PID_FILE"
  exit 0
fi

kill "$PID" 2>/dev/null || true
for _ in $(seq 1 10); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done

if kill -0 "$PID" 2>/dev/null; then
  log "processo resistiu ao SIGTERM — enviando SIGKILL"
  kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE"
log "backend parado."
