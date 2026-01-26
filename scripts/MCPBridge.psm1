# MCP Tool Wrapper Functions for Copilot CLI
# Provides easy-to-call PowerShell functions that invoke MCP tools via detached process

# Global MCP server configuration
$script:MCPServerPath = "c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1"
$script:MCPServerProcess = $null
$script:InitRequestId = 1
$script:NextRequestId = 2
$script:MCPResponses = $null
$script:MCPErrors = $null
$script:OutputReaderJob = $null
$script:ErrorReaderJob = $null

function Start-MCPServerProcess {
    <#
    .SYNOPSIS
        Starts the MCP server as a detached background process
    #>
    
    if ($script:MCPServerProcess -and -not $script:MCPServerProcess.HasExited) {
        Write-Verbose "MCP server already running (PID: $($script:MCPServerProcess.Id))"
        return $script:MCPServerProcess
    }
    
    Write-Host "Starting MCP server..." -ForegroundColor Cyan
    
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "pwsh"
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script:MCPServerPath`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    
    # Set up async output reading
    $script:MCPResponses = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    $script:MCPErrors = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    
    $process.Start() | Out-Null
    
    # Start background jobs to read output asynchronously (without event handlers)
    $script:OutputReaderJob = Start-Job -ScriptBlock {
        param($stdout)
        while (-not $stdout.EndOfStream) {
            $line = $stdout.ReadLine()
            if ($line) {
                Write-Output $line
            }
        }
    } -ArgumentList $process.StandardOutput
    
    $script:ErrorReaderJob = Start-Job -ScriptBlock {
        param($stderr)
        while (-not $stderr.EndOfStream) {
            $line = $stderr.ReadLine()
            if ($line) {
                Write-Output $line
            }
        }
    } -ArgumentList $process.StandardError
    
    # Wait for server to start up
    Write-Host "Waiting for server startup..." -ForegroundColor Gray
    Start-Sleep -Seconds 3
    
    # Initialize the connection
    $initRequest = @{
        jsonrpc = "2.0"
        id = $script:InitRequestId
        method = "initialize"
        params = @{
            protocolVersion = "2024-11-05"
            capabilities = @{
                roots = @{ listChanged = $true }
            }
            clientInfo = @{
                name = "copilot-cli-bridge"
                version = "1.0.0"
            }
        }
    } | ConvertTo-Json -Depth 10 -Compress
    
    Write-Verbose "Sending init request"
    $process.StandardInput.WriteLine($initRequest)
    $process.StandardInput.Flush()
    
    # Wait for init response
    $timeout = [DateTime]::Now.AddSeconds(10)
    $initReceived = $false
    while ([DateTime]::Now -lt $timeout -and -not $initReceived) {
        # Check job output
        $jobOutput = Receive-Job -Job $script:OutputReaderJob -Keep
        foreach ($line in $jobOutput) {
            $script:MCPResponses.Enqueue($line)
            Write-Verbose "Queued: $line"
        }
        
        $response = $null
        if ($script:MCPResponses.TryDequeue([ref]$response)) {
            Write-Verbose "Received: $response"
            if ($response -match '"id":\s*1' -and $response -match '"result"') {
                $initReceived = $true
                Write-Host "✓ MCP server initialized" -ForegroundColor Green
                
                # Send initialized notification
                $initialized = @{
                    jsonrpc = "2.0"
                    method = "notifications/initialized"
                } | ConvertTo-Json -Compress
                $process.StandardInput.WriteLine($initialized)
                $process.StandardInput.Flush()
                break
            }
        }
        Start-Sleep -Milliseconds 100
    }
    
    if (-not $initReceived) {
        throw "Failed to initialize MCP server within timeout"
    }
    
    $script:MCPServerProcess = $process
    return $process
}

function Stop-MCPServerProcess {
    <#
    .SYNOPSIS
        Stops the MCP server process
    #>
    
    if ($script:MCPServerProcess -and -not $script:MCPServerProcess.HasExited) {
        Write-Verbose "Stopping MCP server process..."
        try {
            $script:MCPServerProcess.StandardInput.Close()
            $script:MCPServerProcess.WaitForExit(2000)
            if (-not $script:MCPServerProcess.HasExited) {
                $script:MCPServerProcess.Kill()
            }
            
            # Stop background jobs
            if ($script:OutputReaderJob) {
                Stop-Job -Job $script:OutputReaderJob
                Remove-Job -Job $script:OutputReaderJob -Force
                $script:OutputReaderJob = $null
            }
            if ($script:ErrorReaderJob) {
                Stop-Job -Job $script:ErrorReaderJob
                Remove-Job -Job $script:ErrorReaderJob -Force
                $script:ErrorReaderJob = $null
            }
            
            Write-Host "✓ MCP server stopped" -ForegroundColor Gray
        } catch {
            Write-Verbose "Error stopping server: $_"
        }
        $script:MCPServerProcess = $null
    }
}

function Invoke-MCPToolDirect {
    <#
    .SYNOPSIS
        Invokes an MCP tool using a persistent server process
    
    .PARAMETER ToolName
        Name of the MCP tool to invoke
    
    .PARAMETER Arguments
        Hashtable of arguments to pass to the tool
    
    .PARAMETER KeepServerRunning
        If true, keeps the server running after the call
    
    .EXAMPLE
        Invoke-MCPToolDirect -ToolName "list_tools"
    #>
    param(
        [Parameter(Mandatory=$false)]
        [string]$ToolName,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$Arguments = @{},
        
        [Parameter(Mandatory=$false)]
        [switch]$KeepServerRunning
    )
    
    try {
        # Start or reuse server process
        $process = Start-MCPServerProcess
        
        # Build request
        $requestId = $script:NextRequestId++
        
        if ([string]::IsNullOrEmpty($ToolName)) {
            $request = @{
                jsonrpc = "2.0"
                id = $requestId
                method = "tools/list"
            } | ConvertTo-Json -Depth 10 -Compress
        } else {
            $request = @{
                jsonrpc = "2.0"
                id = $requestId
                method = "tools/call"
                params = @{
                    name = $ToolName
                    arguments = $Arguments
                }
            } | ConvertTo-Json -Depth 10 -Compress
        }
        
        Write-Verbose "Sending request: $request"
        $process.StandardInput.WriteLine($request)
        $process.StandardInput.Flush()
        
        # Wait for response
        $timeout = [DateTime]::Now.AddSeconds(30)
        $responses = @()
        
        while ([DateTime]::Now -lt $timeout) {
            # Check job output
            $jobOutput = Receive-Job -Job $script:OutputReaderJob -Keep
            foreach ($line in $jobOutput) {
                if (-not $script:MCPResponses.Contains($line)) {
                    $script:MCPResponses.Enqueue($line)
                    Write-Verbose "Queued: $line"
                }
            }
            
            $line = $null
            if ($script:MCPResponses.TryDequeue([ref]$line)) {
                Write-Verbose "Received line: $line"
                
                if ($line.StartsWith('{') -and $line.Contains('"jsonrpc"')) {
                    try {
                        $json = $line | ConvertFrom-Json
                        if ($json.id -eq $requestId) {
                            $responses += $json
                            break
                        }
                    } catch {
                        Write-Verbose "Failed to parse JSON: $_"
                    }
                }
            }
            Start-Sleep -Milliseconds 50
        }
        
        if ($responses.Count -gt 0) {
            $response = $responses[0]
            
            if ($response.result) {
                # Format output
                if ($response.result.tools) {
                    Write-Host "`nAvailable MCP Tools:" -ForegroundColor Cyan
                    Write-Host "===================" -ForegroundColor Cyan
                    foreach ($tool in $response.result.tools) {
                        Write-Host "`n• $($tool.name)" -ForegroundColor Yellow
                        if ($tool.description) {
                            Write-Host "  $($tool.description)" -ForegroundColor Gray
                        }
                        if ($tool.inputSchema -and $tool.inputSchema.properties) {
                            Write-Host "  Parameters:" -ForegroundColor DarkGray
                            foreach ($prop in $tool.inputSchema.properties.PSObject.Properties) {
                                $required = if ($tool.inputSchema.required -contains $prop.Name) { " (required)" } else { "" }
                                Write-Host "    - $($prop.Name)$required" -ForegroundColor DarkGray
                            }
                        }
                    }
                } elseif ($response.result.content) {
                    Write-Host "`n✓ Tool executed successfully" -ForegroundColor Green
                    foreach ($content in $response.result.content) {
                        if ($content.type -eq "text") {
                            Write-Host $content.text
                        }
                    }
                }
                
                return $response.result | ConvertTo-Json -Depth 10
            } elseif ($response.error) {
                Write-Host "`n✗ Error: $($response.error.message)" -ForegroundColor Red
                return $response.error | ConvertTo-Json -Depth 10
            }
        } else {
            Write-Host "✗ Timeout waiting for response from MCP server" -ForegroundColor Red
            
            # Show any errors from stderr
            $errorCount = 0
            $error = $null
            while ($script:MCPErrors.TryDequeue([ref]$error) -and $errorCount++ -lt 10) {
                Write-Host "  $error" -ForegroundColor DarkGray
            }
        }
    } finally {
        if (-not $KeepServerRunning) {
            Stop-MCPServerProcess
        }
    }
}

# Convenient aliases
function Get-MCPTools {
    <#
    .SYNOPSIS
        Lists all available MCP tools
    #>
    Invoke-MCPToolDirect -KeepServerRunning
}

function Invoke-MCPTool {
    <#
    .SYNOPSIS
        Invokes a specific MCP tool
    
    .PARAMETER Name
        Name of the tool
    
    .PARAMETER Arguments
        Arguments for the tool
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$Name,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$Arguments = @{}
    )
    
    Invoke-MCPToolDirect -ToolName $Name -Arguments $Arguments -KeepServerRunning
}

# Cleanup on module removal
$MyInvocation.MyCommand.ScriptBlock.Module.OnRemove = {
    Stop-MCPServerProcess
}

# Export functions
Export-ModuleMember -Function Get-MCPTools, Invoke-MCPTool, Invoke-MCPToolDirect, Start-MCPServerProcess, Stop-MCPServerProcess
