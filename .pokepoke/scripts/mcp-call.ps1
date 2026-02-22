#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Helper script to call MCP server tools via JSON-RPC over stdio
.DESCRIPTION
    This script communicates with an MCP server using JSON-RPC 2.0 protocol over stdio.
    It handles the protocol details and provides a simple interface to call tools.
.PARAMETER ServerPath
    Path to the MCP server start script
.PARAMETER Method
    JSON-RPC method to call (e.g., "tools/list", "tools/call")
.PARAMETER ToolName
    Name of the tool to call (only for "tools/call" method)
.PARAMETER Arguments
    JSON string of arguments to pass to the tool
.EXAMPLE
    .\mcp-call.ps1 -ServerPath "c:\path\to\start-mcp-server.ps1" -Method "tools/list"
.EXAMPLE
    .\mcp-call.ps1 -ServerPath "c:\path\to\start-mcp-server.ps1" -Method "tools/call" -ToolName "get_incidents" -Arguments '{}'
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerPath,
    
    [Parameter(Mandatory=$true)]
    [ValidateSet("initialize", "tools/list", "tools/call")]
    [string]$Method,
    
    [Parameter(Mandatory=$false)]
    [string]$ToolName,
    
    [Parameter(Mandatory=$false)]
    [string]$Arguments = '{}'
)

$ErrorActionPreference = "Stop"

# Generate unique request ID
$requestId = [guid]::NewGuid().ToString()

# Build JSON-RPC request based on method
$request = @{
    jsonrpc = "2.0"
    id = $requestId
    method = $Method
}

# Add params based on method type
switch ($Method) {
    "initialize" {
        $request["params"] = @{
            protocolVersion = "2024-11-05"
            capabilities = @{
                tools = @{}
            }
            clientInfo = @{
                name = "pokepoke-mcp-helper"
                version = "1.0.0"
            }
        }
    }
    "tools/call" {
        if (-not $ToolName) {
            throw "ToolName is required for tools/call method"
        }
        $argsObj = $Arguments | ConvertFrom-Json
        $request["params"] = @{
            name = $ToolName
            arguments = $argsObj
        }
    }
    "tools/list" {
        # No params needed for tools/list
    }
}

# Convert request to JSON
$requestJson = $request | ConvertTo-Json -Depth 10 -Compress

try {
    # Start MCP server process
    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = "pwsh"
    $processInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ServerPath`""
    $processInfo.RedirectStandardInput = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processInfo
    $null = $process.Start()
    
    # Wait for server initialization (build + startup takes about 5-10 seconds)
    Start-Sleep -Seconds 8
    
    # Send initialize request first (required by MCP protocol)
    if ($Method -ne "initialize") {
        $initRequest = @{
            jsonrpc = "2.0"
            id = [guid]::NewGuid().ToString()
            method = "initialize"
            params = @{
                protocolVersion = "2024-11-05"
                capabilities = @{
                    tools = @{}
                }
                clientInfo = @{
                    name = "pokepoke-mcp-helper"
                    version = "1.0.0"
                }
            }
        } | ConvertTo-Json -Depth 10 -Compress
        
        $process.StandardInput.WriteLine($initRequest)
        $process.StandardInput.Flush()
        
        # Read and discard initialize response
        $initResponse = $process.StandardOutput.ReadLine()
    }
    
    # Send actual request
    $process.StandardInput.WriteLine($requestJson)
    $process.StandardInput.Flush()
    
    # Read response - filter out non-JSON lines (server logs)
    # MCP servers often emit logging to stdout before JSON responses
    $response = $null
    $attempts = 0
    $maxAttempts = 50  # Read up to 50 lines looking for JSON
    
    while ($attempts -lt $maxAttempts -and $null -eq $response) {
        $line = $process.StandardOutput.ReadLine()
        if ($null -eq $line) {
            break
        }
        
        # Try to parse as JSON - if it works, this is the response
        try {
            $testParse = $line | ConvertFrom-Json -ErrorAction Stop
            if ($testParse.jsonrpc -eq "2.0") {
                $response = $line
                break
            }
        } catch {
            # Not JSON or not JSON-RPC, skip this line
        }
        
        $attempts++
    }
    
    # Now close stdin to signal we're done
    $process.StandardInput.Close()
    
    # Wait for process to exit (with timeout)
    $null = $process.WaitForExit(5000)
    
    if ($null -eq $response -or $response -eq "") {
        $stderr = $process.StandardError.ReadToEnd()
        throw "No response from MCP server after reading $attempts lines. Error: $stderr"
    }
    
    # Parse and return response
    $responseObj = $response | ConvertFrom-Json
    
    if ($responseObj.error) {
        throw "MCP Error: $($responseObj.error.message) (Code: $($responseObj.error.code))"
    }
    
    # Return just the result
    if ($responseObj.result) {
        $responseObj.result | ConvertTo-Json -Depth 10
    } else {
        $response
    }
    
} catch {
    Write-Error "Failed to call MCP server: $_"
    exit 1
} finally {
    if ($process -and -not $process.HasExited) {
        $process.Kill()
    }
}
