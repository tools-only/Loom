@echo off
REM Start the Anchor Service (http://localhost:3000) in the background.
REM Run once; survives Claude Code restarts. Keep open to see logs.

cd /d "%~dp0.."

REM Start Anchor if not running
curl -s http://localhost:3000/health >nul 2>&1
if %errorlevel% == 0 (
  echo Anchor service already running on http://localhost:3000
) else (
  echo Starting Anchor service on http://localhost:3000 ...
  set ANCHOR_USE_AUTOEXEC=1
  set ANCHOR_DISABLE_ENRICHMENT=1
  start "Anchor Service" /MIN cmd /c "node mcp\server.cjs"
)

REM Start Loom Brain (FastAPI) if not running
curl -s http://localhost:3002/health >nul 2>&1
if %errorlevel% == 0 (
  echo Loom Brain already running on http://localhost:3002
) else (
  echo Starting Loom Brain on http://localhost:3002 ...
  REM Codex SDK needs the same writable CODEX_HOME used by the logged-in CLI.
  REM In this portable D: layout, Codex state lives beside the workspace root.
  if not defined CODEX_HOME if exist "%~d0\agent\.codex\auth.json" set "CODEX_HOME=%~d0\agent\.codex"
  if not defined LOOM_CODEX_HOME set "LOOM_CODEX_HOME=%CODEX_HOME%"
  REM Clear cc-switch routing so Brain reaches api.anthropic.com via Veee HTTPS_PROXY
	  start "Loom Brain" /MIN cmd /c "set ANTHROPIC_BASE_URL=&& set ANTHROPIC_AUTH_TOKEN=&& cd loom && D:\conda\python.exe main.py"
)

REM Start enabled social channel bridge bots if not running
curl -s http://localhost:3015/health >nul 2>&1
if %errorlevel% == 0 (
  echo Loom Channel Bridges already running on http://localhost:3015
) else (
  echo Starting Loom Channel Bridges on http://localhost:3015 ...
  set "LOOM_BRAIN_URL=http://127.0.0.1:3002"
  start "Loom Channel Bridges" /MIN cmd /c "node bridge\channels\launcher.cjs"
)

timeout /t 2 /nobreak >nul
start "" http://localhost:3000
echo Done. Anchor on :3000, Loom Core on :3001, Loom Brain on :3002, Channel Bridges on :3015.
