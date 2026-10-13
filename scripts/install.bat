@echo off
rem Instala backend (venv + pacote) e frontend (node_modules) no Windows.
setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo [pandora] ERRO: python nao encontrado no PATH ^(precisa 3.12+^)
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [pandora] ERRO: npm nao encontrado ^(precisa Node 20+^)
  exit /b 1
)

if not exist backend\.venv (
  echo [pandora] criando venv em backend\.venv
  python -m venv backend\.venv || exit /b 1
)

echo [pandora] instalando backend
backend\.venv\Scripts\python -m pip install --upgrade pip || exit /b 1
backend\.venv\Scripts\pip install -e backend || exit /b 1

echo [pandora] instalando frontend
pushd frontend
if exist package-lock.json (npm ci) else (npm install)
set "NPM_ERR=%errorlevel%"
popd
if not "%NPM_ERR%"=="0" exit /b %NPM_ERR%

echo [pandora] instalacao concluida.
echo [pandora] proximo passo: scripts\run.bat
exit /b 0
