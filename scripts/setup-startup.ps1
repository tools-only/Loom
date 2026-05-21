# Register Anchor Service to auto-start at Windows login.
# Option A (recommended): PM2 — survives crashes, restarts automatically.
# Option B: Windows Task Scheduler — no extra tools needed.
#
# Run from the repo root or scripts\ folder.

$root = Split-Path $PSScriptRoot

# ── Option A: PM2 ──────────────────────────────────────────────────────
Write-Host "Checking for PM2..." -ForegroundColor Cyan
if (Get-Command pm2 -ErrorAction SilentlyContinue) {
    Write-Host "PM2 found. Registering Anchor service..."
    Set-Location $root
    pm2 start mcp/server.cjs --name anchor --cwd $root
    pm2 save
    Write-Host ""
    Write-Host "Run the following command (as Administrator) to enable auto-start at login:" -ForegroundColor Yellow
    pm2 startup
    Write-Host ""
    Write-Host "Done. Use 'pm2 logs anchor' to see service logs." -ForegroundColor Green
    exit
}

# ── Option B: Task Scheduler ───────────────────────────────────────────
Write-Host "PM2 not found. Installing PM2 is recommended (npm install -g pm2)."
Write-Host "Falling back to Windows Task Scheduler..."

$nodeExe = (Get-Command node -ErrorAction SilentlyContinue)?.Source
if (-not $nodeExe) {
    Write-Host "ERROR: node.exe not found in PATH." -ForegroundColor Red
    exit 1
}

$taskName = "AnchorService"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$action   = New-ScheduledTaskAction `
    -Execute $nodeExe `
    -Argument "mcp\server.cjs" `
    -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Task '$taskName' registered. Service will start at next login." -ForegroundColor Green
Write-Host "To start now: scripts\start-anchor.bat"
