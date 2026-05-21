@echo off
REM Start the Anchor Service (http://localhost:3000) in the background.
REM Run once; survives Claude Code restarts. Keep open to see logs.

cd /d "%~dp0.."

REM Check if already running
curl -s http://localhost:3000/health >nul 2>&1
if %errorlevel% == 0 (
  echo Anchor service already running on http://localhost:3000
  start "" http://localhost:3000
  exit /b 0
)

echo Starting Anchor service on http://localhost:3000 ...
set ANCHOR_USE_AUTOEXEC=1
start "Anchor Service" /MIN cmd /c "node mcp\server.cjs"
timeout /t 2 /nobreak >nul
start "" http://localhost:3000
echo Done. Claude Code will now connect via mcp/shim.cjs automatically.
