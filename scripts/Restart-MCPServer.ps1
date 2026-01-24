#!/usr/bin/env pwsh
# Restart the MCP HTTP Server
# Usage: .\Restart-MCPServer.ps1 [-Port 8080] [-HostName 0.0.0.0]

param(
    [int]$Port = 8080,
    [string]$HostName = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Restarting MCP HTTP Server ===" -ForegroundColor Magenta
Write-Host ""

# Stop any existing server on the port
Write-Host "1. Stopping existing server on port $Port..." -ForegroundColor Cyan
$connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($connections) {
    foreach ($conn in $connections) {
        $processId = $conn.OwningProcess
        Write-Host "   Stopping process $processId" -ForegroundColor Yellow
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

# Stop any background jobs running the server
Write-Host "2. Stopping background jobs..." -ForegroundColor Cyan
$jobs = Get-Job | Where-Object { $_.Command -like "*start-mcp-server-http*" }
if ($jobs) {
    $jobs | Stop-Job
    $jobs | Remove-Job
    Write-Host "   Stopped $($jobs.Count) background job(s)" -ForegroundColor Yellow
}

# Verify port is free
$stillListening = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($stillListening) {
    Write-Host "   ✗ Port $Port still in use, waiting..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

# Start the server in a background job
Write-Host "3. Starting new server..." -ForegroundColor Cyan
$serverScript = "C:\Users\ameliapayne\icm_queue_c#\start-mcp-server-http.ps1"

if (-not (Test-Path $serverScript)) {
    Write-Host "   ✗ Server script not found: $serverScript" -ForegroundColor Red
    exit 1
}

$job = Start-Job -ScriptBlock {
    param($scriptPath, $portNum, $hostName)
    Set-Location (Split-Path $scriptPath -Parent)
    & $scriptPath -Port $portNum -HostName $hostName
} -ArgumentList $serverScript, $Port, $HostName

Write-Host "   Started job ID: $($job.Id)" -ForegroundColor Green

# Wait for server to be ready
Write-Host "4. Waiting for server to be ready..." -ForegroundColor Cyan
$maxAttempts = 20
$attempt = 0
$ready = $false

while ($attempt -lt $maxAttempts -and -not $ready) {
    Start-Sleep -Seconds 2  # Increased from 1 to 2 seconds
    $attempt++
    
    # Check if job is still running
    $jobState = (Get-Job -Id $job.Id -ErrorAction SilentlyContinue).State
    if ($jobState -ne "Running") {
        Write-Host "   Job stopped unexpectedly (State: $jobState)" -ForegroundColor Red
        break
    }
    
    # Use netstat to check port (more reliable than Get-NetTCPConnection)
    $netstat = netstat -ano 2>$null | Select-String ":$Port\s"
    if ($netstat -and $netstat -match "LISTENING") {
        $ready = $true
    } else {
        Write-Host "   Attempt $attempt/$maxAttempts..." -ForegroundColor Gray
    }
}

Write-Host ""
if ($ready) {
    Write-Host "✓ MCP Server is ready!" -ForegroundColor Green
    Write-Host "  URL: http://localhost:$Port" -ForegroundColor Cyan
    Write-Host "  Job ID: $($job.Id)" -ForegroundColor Gray
} else {
    Write-Host "✗ Server did not start successfully" -ForegroundColor Red
    Write-Host "  Check job output with: Receive-Job $($job.Id)" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "To test the server:" -ForegroundColor Gray
Write-Host "  copilot -p 'List MCP tools' --allow-all-tools --no-ask-user" -ForegroundColor DarkGray
