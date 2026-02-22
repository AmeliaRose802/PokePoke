# Start MCP Server as a persistent background service
# Usage: .\Start-MCPServer.ps1

$serverPath = "c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1"
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
