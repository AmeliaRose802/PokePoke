# Start MCP Server as a persistent background service
# Usage: .\Start-MCPServer.ps1 [-ServerPath <path>]

param(
    [string]$ServerPath
)

# Resolve server path: parameter > environment variable > error
if (-not $ServerPath) {
    $ServerPath = $env:MCP_SERVER_PATH
}

if (-not $ServerPath) {
    Write-Host "✗ Server path not specified." -ForegroundColor Red
    Write-Host "  Set MCP_SERVER_PATH environment variable or use -ServerPath parameter" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $ServerPath)) {
    Write-Host "✗ Server script not found: $ServerPath" -ForegroundColor Red
    exit 1
}

$serverPath = $ServerPath
$pidFile = "$PSScriptRoot\mcp-server.pid"
$logFile = "$PSScriptRoot\mcp-server.log"

# Check if server is already running
if (Test-Path $pidFile) {
    $pid = Get-Content $pidFile
    if (Get-Process -Id $pid -ErrorAction SilentlyContinue) {
        Write-Host "✓ MCP Server already running (PID: $pid)" -ForegroundColor Green
        exit 0
    }
}

# Start server
Write-Host "Starting MCP Server..." -ForegroundColor Cyan

$process = Start-Process pwsh `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $serverPath `
    -PassThru `
    -RedirectStandardOutput $logFile `
    -WindowStyle Hidden

# Save PID
$process.Id | Set-Content $pidFile

Write-Host "✓ MCP Server started (PID: $($process.Id))" -ForegroundColor Green
Write-Host "  Log: $logFile" -ForegroundColor Gray
Write-Host "  Use Stop-MCPServer.ps1 to stop" -ForegroundColor Gray

return $process.Id
