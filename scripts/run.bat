@echo off
rem Sobe o backend (FastAPI) em janela propria, servindo tambem o build do frontend.
setlocal
cd /d "%~dp0.."

if not exist backend\.venv\Scripts\python.exe (
  echo [pandora] ERRO: venv nao encontrado - rode scripts\install.bat
  exit /b 1
)

rem Carrega .env da raiz (ignora linhas vazias/comentario) e traduz PANDORA_* para
rem as variaveis que o backend le (HOST, PORT, DATA_DIR, ...).
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)
if defined PANDORA_HOST set "HOST=%PANDORA_HOST%"
if defined PANDORA_PORT set "PORT=%PANDORA_PORT%"
if defined PANDORA_DATA_DIR set "DATA_DIR=%PANDORA_DATA_DIR%"
if defined PANDORA_DB_FILENAME set "DB_FILENAME=%PANDORA_DB_FILENAME%"
if defined PANDORA_DEV_ORIGIN set "DEV_ORIGIN=%PANDORA_DEV_ORIGIN%"
if defined PANDORA_MAX_FILE_SIZE_BYTES set "MAX_FILE_SIZE_BYTES=%PANDORA_MAX_FILE_SIZE_BYTES%"
if defined PANDORA_MAX_FILES set "MAX_FILES=%PANDORA_MAX_FILES%"
if defined PANDORA_MAX_DEPTH set "MAX_DEPTH=%PANDORA_MAX_DEPTH%"
if not defined PORT set "PORT=8000"
if not defined HOST set "HOST=127.0.0.1"

if not exist frontend\dist\index.html (
  echo [pandora] frontend\dist ausente - rodando build
  pushd frontend
  call npm run build
  set "BUILD_ERR=%errorlevel%"
  popd
  if not "%BUILD_ERR%"=="0" exit /b %BUILD_ERR%
)

echo [pandora] subindo backend em http://%HOST%:%PORT%
start "Pandora Architect" /min cmd /c "cd /d backend && .venv\Scripts\python -m uvicorn app.main:app --host %HOST% --port %PORT% --log-level info"
echo [pandora] aguardando /api/health...
set /a _try=0
:wait
set /a _try+=1
curl -fsS --max-time 2 "http://127.0.0.1:%PORT%/api/health" >nul 2>nul
if not errorlevel 1 (
  echo [pandora] ok -^> http://127.0.0.1:%PORT%
  exit /b 0
)
if %_try% geq 30 (
  echo [pandora] ERRO: backend nao respondeu em 30s ^(veja a janela "Pandora Architect"^)
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait
