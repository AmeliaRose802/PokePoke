# Stop MCP Server
# Usage: .\Stop-MCPServer.ps1

$pidFile = "$PSScriptRoot\mcp-server.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "No server PID file found" -ForegroundColor Yellow
    exit 0
}

$pid = Get-Content $pidFile

$process = Get-Process -Id $pid -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $pid -Force
    Write-Host "✓ MCP Server stopped (PID: $pid)" -ForegroundColor Green
} else {
    Write-Host "Server process not running" -ForegroundColor Yellow
}

Remove-Item $pidFile -ErrorAction SilentlyContinue
