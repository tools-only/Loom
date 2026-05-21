@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BASH_EXE="

if exist "D:\Git\bin\bash.exe" set "BASH_EXE=D:\Git\bin\bash.exe"
if not defined BASH_EXE (
  for %%B in (bash.exe) do (
    if not defined BASH_EXE set "BASH_EXE=%%~$PATH:B"
  )
)

if defined BASH_EXE (
  "%BASH_EXE%" "%SCRIPT_DIR%stop-anchor.sh"
  exit /b %errorlevel%
)

echo [anchor-stop] Git Bash not found; using Node fallback
node "%SCRIPT_DIR%stop-anchor-helper.cjs"
exit /b %errorlevel%
