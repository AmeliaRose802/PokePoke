Your job is to address a specific beads item on your subtree then commit making sure all validation passes. 

You are working on item: {{item_id}}

**Title:** {{title}}

**Description:**
{{description}}

**Type:** {{issue_type}}
**Priority:** {{priority}}
{{#labels}}
**Labels:** {{labels}}
{{/labels}}


**Additional Context:**
Use these beads commands to get more information if needed:
- `bd show {{item_id}} --json` - View full item details
- `bd list --deps {{item_id}} --json` - Check dependencies
- `bd list --label <label> --json` - Find related items by label

**MCP Server Testing:**
If this work item involves modifying the ICM MCP Server (`C:\Users\ameliapayne\icm_queue_c#`):
1. Make and commit your code changes to the MCP server
2. Restart the MCP server to load your changes:
   ```powershell
   rmcp  # or Restart-MCP for full output
   ```
3. Verify your changes by actually using the modified MCP tool:
   - Use the MCP tool directly to test it works correctly
   - Try the specific scenario that was broken before your fix
   - Verify the tool returns the expected results
4. If the test fails, make additional changes, commit, and repeat steps 2-3 until it works

The `rmcp` and `Restart-MCP` commands are automatically available - no setup needed!

## Restarting the MCP Server Over HTTP

The MCP server needs to be restarted whenever you make code changes.

### Quick Start

**1. Restart the server:**
```powershell
.\scripts\Restart-MCPServer.ps1
```

This automatically:
- Stops existing servers on the port
- Starts new server in background job
- Waits for server to be ready
- Verifies server is responding

**2. Test the server is working:**
```powershell
.\scripts\Test-MCPServer.ps1
```

### Calling MCP Tools from PowerShell

**Simple tool invocation helper:**
```powershell
# Tool with no parameters
.\scripts\Invoke-MCPTool.ps1 -Tool "check_kusto_health"

# Tool with parameters
.\scripts\Invoke-MCPTool.ps1 -Tool "get_incident_context" -Params @{incidentId=731982504}

# List available queries
.\scripts\Invoke-MCPTool.ps1 -Tool "list_kusto_queries" -Params @{category="heartbeat"; includeParameters=$true}

# Show raw SSE response
.\scripts\Invoke-MCPTool.ps1 -Tool "check_kusto_health" -ShowRaw
```

**Manual tool call (if you need full control):**
```powershell
$body = @{
    jsonrpc = "2.0"
    id = 1
    method = "tools/call"
    params = @{
        name = "get_incident_context"
        arguments = @{
            incidentId = 731982504
        }
    }
} | ConvertTo-Json -Depth 10

$headers = @{
    "Content-Type" = "application/json"
    "Accept" = "application/json, text/event-stream"
}

Invoke-RestMethod -Uri "http://localhost:5000" -Method Post -Body $body -Headers $headers
```

### Troubleshooting

**Check server status:**
```powershell
# Check if port is listening
Get-NetTCPConnection -LocalPort 5000 -State Listen

# Get background job status (use job ID from restart script)
Get-Job
Receive-Job <job-id>  # See server output/errors
```

**Common Issues:**
- **Build failures**: Check the restart script output for build errors
- **Configuration missing**: Copy `appsettings.example.json` to `appsettings.json`
- **Server won't start**: Use `Receive-Job <job-id>` to see detailed error messages
- **Port in use**: The restart script kills existing processes automatically
- **Headers required**: Server requires `Accept: application/json, text/event-stream`

**Kill all servers and start fresh:**
```powershell
Get-NetTCPConnection -LocalPort 5000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
.\scripts\Restart-MCPServer.ps1
```

## Test data


When you need an incident to test with, use: https://portal.microsofticm.com/imp/v5/incidents/details/737661947/summary

When you need a VM Id, use: 14b9cc89-0c2d-4884-a7b7-ff83270592cd

When you need a containerID use: d3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a

Use incident time: 2026-01-23T20:14:55.9797441Z

**Success Criteria:**
- Provided item is fully implemented
- If MCP tools were modified, they have been tested manually and work correctly
- All pre-commit validation passes successfully
- All changes are committed and the worktree has been merged

## Test data

When you need an incident to test with, use: https://portal.microsofticm.com/imp/v5/incidents/details/737661947/summary

When you need a VM Id, use: 14b9cc89-0c2d-4884-a7b7-ff83270592cd

When you need a containerID use: d3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a

Use incident time: 2026-01-23T20:14:55.9797441Z

## If it is already completed

Close the beads item

## When you finish it

Close the beads item