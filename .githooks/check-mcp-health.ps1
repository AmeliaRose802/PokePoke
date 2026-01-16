#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check if the MCP server can start successfully
    
.DESCRIPTION
    Starts the MCP server with a timeout to verify it initializes without errors.
    This catches common startup issues like configuration errors, dependency injection
    failures, or missing resources before allowing commits.

.EXAMPLE
    .\scripts\check-mcp-health.ps1
#>

$ErrorActionPreference = "Stop"

# Get repository root
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

$projectPath = Join-Path $repoRoot "src\IcmMcpServer\IcmMcpServer.csproj"

if (-not (Test-Path $projectPath)) {
    Write-Host "❌ MCP Server project not found: $projectPath" -ForegroundColor Red
    exit 1
}

Write-Host "🏥 Testing MCP server health..." -ForegroundColor Cyan

# Create temporary files for process I/O
$stderrFile = New-TemporaryFile
$stdoutFile = New-TemporaryFile

try {
    # Start the MCP server process with timeout
    $process = Start-Process -FilePath "dotnet" `
        -ArgumentList "run", "--project", $projectPath, "--configuration", "Debug", "--no-build" `
        -RedirectStandardError $stderrFile.FullName `
        -RedirectStandardOutput $stdoutFile.FullName `
        -PassThru `
        -NoNewWindow

    $timeout = 8  # seconds
    $startTime = Get-Date
    $healthCheckPassed = $false
    
    # Wait for process to start or fail
    while ((Get-Date) -lt $startTime.AddSeconds($timeout)) {
        # Check if process exited with error
        if ($process.HasExited) {
            if ($process.ExitCode -ne 0) {
                $stderrContent = Get-Content $stderrFile.FullName -Raw -ErrorAction SilentlyContinue
                
                Write-Host ""
                Write-Host "❌ MCP SERVER FAILED TO START" -ForegroundColor Red
                Write-Host ""
                Write-Host "Exit code: $($process.ExitCode)" -ForegroundColor Yellow
                
                if ($stderrContent) {
                    Write-Host ""
                    Write-Host "Error output:" -ForegroundColor Yellow
                    $stderrContent -split "`n" | Select-Object -First 20 | ForEach-Object { 
                        if ($_ -match "error|exception|fail") {
                            Write-Host $_ -ForegroundColor Red 
                        }
                    }
                }
                
                Write-Host ""
                Write-Host "Fix the MCP server startup issues before committing." -ForegroundColor Yellow
                Write-Host "Test manually with: .\start-mcp-server.ps1" -ForegroundColor Yellow
                
                # Cleanup
                Remove-Item $stderrFile.FullName -Force -ErrorAction SilentlyContinue
                Remove-Item $stdoutFile.FullName -Force -ErrorAction SilentlyContinue
                exit 1
            }
            # Process exited cleanly (shouldn't happen normally, but acceptable)
            break
        }
        
        # Check stderr for fatal errors even while running
        $stderrContent = Get-Content $stderrFile.FullName -Raw -ErrorAction SilentlyContinue
        if ($stderrContent -match "Unhandled exception|System\.Exception|fail.*to.*start|Configuration error") {
            Write-Host ""
            Write-Host "❌ MCP SERVER STARTUP ERROR DETECTED" -ForegroundColor Red
            Write-Host ""
            $stderrContent -split "`n" | Select-Object -First 15 | ForEach-Object { 
                Write-Host $_ -ForegroundColor Red 
            }
            Write-Host ""
            
            # Kill the process
            if (-not $process.HasExited) {
                $process.Kill()
                $process.WaitForExit(2000)
            }
            
            # Cleanup
            Remove-Item $stderrFile.FullName -Force -ErrorAction SilentlyContinue
            Remove-Item $stdoutFile.FullName -Force -ErrorAction SilentlyContinue
            exit 1
        }
        
        # If process is still running after 3 seconds, consider it healthy
        if ((Get-Date) -gt $startTime.AddSeconds(3)) {
            $healthCheckPassed = $true
            break
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    # Kill the process if still running
    if (-not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit(2000)
    }
    
    if ($healthCheckPassed) {
        Write-Host "✅ MCP server started successfully" -ForegroundColor Green
    }
    else {
        Write-Host "✅ No startup errors detected" -ForegroundColor Green
    }
    
    # Cleanup
    Remove-Item $stderrFile.FullName -Force -ErrorAction SilentlyContinue
    Remove-Item $stdoutFile.FullName -Force -ErrorAction SilentlyContinue
    exit 0
}
catch {
    Write-Host ""
    Write-Host "❌ MCP SERVER HEALTH CHECK FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    
    # Cleanup
    if ($process -and -not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit(2000)
    }
    Remove-Item $stderrFile.FullName -Force -ErrorAction SilentlyContinue
    Remove-Item $stdoutFile.FullName -Force -ErrorAction SilentlyContinue
    exit 1
}
