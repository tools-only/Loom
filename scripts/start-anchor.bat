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
  start "Loom Brain" /MIN cmd /c "cd loom && D:\conda\python.exe main.py"
)

timeout /t 2 /nobreak >nul
start "" http://localhost:3000
echo Done. Anchor on :3000, Loom Core on :3001, Loom Brain on :3002.
