@echo off
REM Start Loom Brain with Veee proxy (no cc-switch)
cd /d "%~dp0..\loom"

REM Route through Veee proxy only, remove broken cc-switch
set HTTPS_PROXY=http://127.0.0.1:15236
set ANTHROPIC_BASE_URL=
set ANTHROPIC_AUTH_TOKEN=

echo Starting Loom Brain on http://localhost:3002 (Veee proxy)...
D:\conda\python.exe main.py
