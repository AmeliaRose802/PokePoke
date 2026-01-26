# MCP Tool Bridge for Copilot CLI
# Allows invocation of stdio-based MCP tools through PowerShell

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerCommand,
    
    [Parameter(Mandatory=$true)]
    [string[]]$ServerArgs,
    
    [Parameter(Mandatory=$false)]
    [string]$ToolName = "",
    
    [Parameter(Mandatory=$false)]
    [hashtable]$Arguments = @{}
)

function Send-MCPRequest {
    param(
        [Parameter(Mandatory=$true)]
        $Process,
        
        [Parameter(Mandatory=$true)]
        [string]$Method,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$Params = @{}
    )
    
    $request = @{
        jsonrpc = "2.0"
        id = Get-Random -Maximum 1000000
        method = $Method
        params = $Params
    } | ConvertTo-Json -Depth 10 -Compress
    
    $Process.StandardInput.WriteLine($request)
    $Process.StandardInput.Flush()
    
    # Read response - may be multiple lines, look for JSON-RPC response
    $timeout = [DateTime]::Now.AddSeconds(5)
    while ([DateTime]::Now -lt $timeout) {
        if ($Process.StandardOutput.Peek() -ge 0) {
            $line = $Process.StandardOutput.ReadLine()
            
            # Skip empty lines and debug output
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            
            # Try to parse as JSON
            try {
                $json = $line | ConvertFrom-Json
                # Check if it's a JSON-RPC response
                if ($json.jsonrpc -eq "2.0" -and ($json.result -or $json.error)) {
                    return $json
                }
            } catch {
                # Not JSON, skip
                Write-Verbose "Skipping non-JSON line: $line"
            }
        }
        Start-Sleep -Milliseconds 100
    }
    
    return $null
}

# Start MCP server process
$processInfo = New-Object System.Diagnostics.ProcessStartInfo
$processInfo.FileName = $ServerCommand
$processInfo.Arguments = $ServerArgs -join " "
$processInfo.RedirectStandardInput = $true
$processInfo.RedirectStandardOutput = $true
$processInfo.RedirectStandardError = $true
$processInfo.UseShellExecute = $false
$processInfo.CreateNoWindow = $true

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $processInfo

try {
    $process.Start() | Out-Null
    Start-Sleep -Seconds 3  # Wait for server to build and start
    
    # Initialize connection
    $initResponse = Send-MCPRequest -Process $process -Method "initialize" -Params @{
        protocolVersion = "2024-11-05"
        capabilities = @{
            roots = @{ listChanged = $true }
            sampling = @{}
        }
        clientInfo = @{
            name = "copilot-cli-bridge"
            version = "1.0.0"
        }
    }
    
    if ($initResponse -and $initResponse.result) {
        Write-Host "✓ Connected to MCP server: $($initResponse.result.serverInfo.name)" -ForegroundColor Green
        
        # Send initialized notification
        $initialized = @{
            jsonrpc = "2.0"
            method = "notifications/initialized"
        } | ConvertTo-Json -Compress
        $process.StandardInput.WriteLine($initialized)
        $process.StandardInput.Flush()
        
        # List tools if no specific tool requested
        if (-not $ToolName) {
            $toolsResponse = Send-MCPRequest -Process $process -Method "tools/list"
            
            if ($toolsResponse -and $toolsResponse.result) {
                Write-Host "`nAvailable Tools:" -ForegroundColor Cyan
                foreach ($tool in $toolsResponse.result.tools) {
                    Write-Host "  • $($tool.name)" -ForegroundColor Yellow
                    if ($tool.description) {
                        Write-Host "    $($tool.description)" -ForegroundColor Gray
                    }
                }
                
                return $toolsResponse.result.tools | ConvertTo-Json -Depth 10
            }
        } else {
            # Invoke specific tool
            $toolResponse = Send-MCPRequest -Process $process -Method "tools/call" -Params @{
                name = $ToolName
                arguments = $Arguments
            }
            
            if ($toolResponse -and $toolResponse.result) {
                Write-Host "✓ Tool invocation successful" -ForegroundColor Green
                
                # Display content
                foreach ($content in $toolResponse.result.content) {
                    if ($content.type -eq "text") {
                        Write-Host $content.text
                    }
                }
                
                return $toolResponse.result | ConvertTo-Json -Depth 10
            } elseif ($toolResponse -and $toolResponse.error) {
                Write-Host "✗ Error: $($toolResponse.error.message)" -ForegroundColor Red
                return $toolResponse.error | ConvertTo-Json -Depth 10
            }
        }
    } else {
        Write-Host "✗ Failed to initialize MCP server" -ForegroundColor Red
        if ($initResponse -and $initResponse.error) {
            Write-Host "Error: $($initResponse.error.message)" -ForegroundColor Red
        }
    }
} finally {
    # Cleanup
    if (-not $process.HasExited) {
        $process.Kill()
    }
    $process.Dispose()
}
