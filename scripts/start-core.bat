@echo off
REM Start the Loom Core Python daemon
REM This runs alongside scripts\start-anchor.bat on port 3001

echo Starting Loom Core runtime (Python) on port 3001...
echo.
"D:\conda\python.exe" -m loom_core
if %ERRORLEVEL% NEQ 0 (
    echo Failed to start Loom Core runtime.
    echo Make sure Python 3.11+ is available at D:\conda\python.exe
    pause
    exit /b 1
)
