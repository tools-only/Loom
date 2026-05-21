@echo off
cd /d "%~dp0.."
if "%~1"=="" (
  echo Usage: start-subagent.bat [agent-id]
  echo Example: start-subagent.bat writer
  echo.
  echo Starts a persistent AI subagent that connects to the Anchor service
  echo at ws://localhost:3000/ws/agent?agentId=[agent-id]
  echo.
  echo The subagent runs its own WebSocket + AI loop via Node.js.
  echo It does NOT require a Claude Code CLI session.
  exit /b 1
)
set ANCHOR_AGENT_ID=%~1
set ANCHOR_PORT=3000
echo Starting subagent '%ANCHOR_AGENT_ID%' ...
echo Connecting to ws://localhost:3000/ws/agent?agentId=%ANCHOR_AGENT_ID%
echo.
echo [Subagent loop: anchor_await_op -^> AI generate -^> anchor_patch -^> repeat]
echo.
node mcp\subagent-loop.cjs
pause