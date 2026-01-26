#!/usr/bin/env pwsh
# Load PowerShell aliases for PokePoke agents
# Add to your PowerShell profile: . C:\Users\ameliapayne\PokePoke\scripts\Load-AgentAliases.ps1

$scriptRoot = Split-Path -Parent $PSCommandPath

# Restart MCP Server alias
function Global:Restart-MCP {
    <#
    .SYNOPSIS
    Restart the MCP HTTP Server for testing tool changes
    
    .DESCRIPTION
    Stops any running MCP server and starts a fresh instance on port 8080.
    Use this after modifying MCP server code to test your changes.
    
    .PARAMETER Port
    Port to run the server on (default: 8080)
    
    .PARAMETER HostName
    Host name to bind to (default: 0.0.0.0)
    
    .EXAMPLE
    Restart-MCP
    
    .EXAMPLE
    Restart-MCP -Port 9000
    #>
    param(
        [int]$Port = 8080,
        [string]$HostName = "0.0.0.0"
    )
    
    & "$scriptRoot\Restart-MCPServer.ps1" -Port $Port -HostName $HostName
}

# Alias for convenience
Set-Alias -Name rmcp -Value Restart-MCP -Scope Global

# Only show output if running interactively
if (-not $env:CI -and -not $env:COPILOT_NON_INTERACTIVE) {
    Write-Host "✓ PokePoke agent aliases loaded" -ForegroundColor Green
    Write-Host "  Commands available:" -ForegroundColor Gray
    Write-Host "    Restart-MCP   - Restart MCP HTTP Server" -ForegroundColor Cyan
    Write-Host "    rmcp          - Alias for Restart-MCP" -ForegroundColor Cyan
}
