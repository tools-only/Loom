@echo off
REM Start Loom Desktop Float (native Windows floating capture window)
REM This is a standalone background process independent from the Electron app.

cd /d "%~dp0.."

echo Starting Loom Desktop Float...

REM Use conda Python (modify path if needed)
set "PYTHON=D:\conda\python.exe"
set "SCRIPT=desktop_float\float.py"

if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    echo Edit scripts\start-float.bat to point to your Python executable.
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo ERROR: Script not found at %SCRIPT%
    pause
    exit /b 1
)

REM Start in background (minimized console window)
start "Loom Desktop Float" /MIN "%PYTHON%" "%SCRIPT%"

echo Loom Desktop Float started in background.
echo Use the floating ball on your desktop to capture resources.
echo.
echo To quit: close the Python process from Task Manager.
