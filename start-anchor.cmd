@echo off
cd /d "%~dp0"
echo Starting Loom MCP Server on http://localhost:3000
echo Open this URL in your browser, then return to Claude Code.
echo.
echo NOTE: The MCP server auto-starts with Claude Code.
echo       Only run this script if you need a standalone instance.
echo.
node mcp\server.cjs
pause
