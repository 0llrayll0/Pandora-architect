#!/usr/bin/env bash
# Instala backend (venv + pacote) e frontend (node_modules).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

log "Python: $(command -v python3 >/dev/null && python3 --version || echo 'não encontrado')"
command -v python3 >/dev/null || die "python3 não encontrado"
command -v node >/dev/null || die "node não encontrado (instale Node 20+)"
command -v npm >/dev/null || die "npm não encontrado"

# --- backend ---------------------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "criando venv em backend/.venv"
  python3 -m venv "$VENV_DIR"
fi

if command -v uv >/dev/null 2>&1; then
  log "instalando backend com uv (dev group incluído)"
  uv pip install --python "$VENV_DIR/bin/python" -e "$BACKEND_DIR" --group dev
else
  log "uv não encontrado — instalando com pip (só runtime)"
  "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
  "$VENV_DIR/bin/pip" install -e "$BACKEND_DIR"
fi

# --- frontend --------------------------------------------------------------
log "instalando dependências do frontend"
cd "$FRONTEND_DIR"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

log "instalação concluída."
log "próximo passo: scripts/run.sh (produção) ou scripts/dev.sh (desenvolvimento)"
