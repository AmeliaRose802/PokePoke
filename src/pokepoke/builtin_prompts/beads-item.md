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

{{#retry_feedback}}

## ⚠️ PREVIOUS ATTEMPT FEEDBACK

The following feedback was provided by previous gate-agent or retry checks. **Address all of these issues in your implementation:**

{{retry_feedback}}
{{/retry_feedback}}

## ⚠️ CRITICAL: Avoiding Hung Commands

**Command Timeout: {{command_timeout}} seconds**

Long-running commands can hang indefinitely, wasting time. Follow these rules:

1. **Always use timeouts for pytest:**
   ```powershell
   pytest --timeout={{command_timeout}}
   ```
   NEVER run bare `pytest` without --timeout flag.

2. **For targeted test runs, still use --timeout:**
   ```powershell
   pytest tests/test_specific_module.py --timeout={{command_timeout}}
   ```
   Running specific test files is faster and less likely to hang.

3. **If a test run times out, retry with -x --timeout=15:**
   ```powershell
   pytest -x --timeout=15
   ```
   This helps identify the specific hanging test by stopping on first failure with a shorter timeout.

4. **NEVER use Select-Object -First/-Last:**
   These flags can hang PowerShell pipelines. Use safe alternatives instead:
   ```powershell
   Get-Content file.txt -Head 10
   Get-Content file.txt -Tail 5
   $lines = Get-Content file.txt
   $lines[0..9]
   ```

5. **If a command appears stuck:**
   - After 2-3 `read_powershell` calls with no new output, the command is likely hung
   - Use `stop_powershell` to kill the hung process
   - Retry with a timeout flag or run targeted tests instead

6. **For builds/installs:**
   Use reasonable initial_wait values and be prepared to stop if hung.

7. **When writing tests that touch subprocess/git/filesystem:**
   Use mocks or explicit timeouts. Avoid integration tests that run real operations without timeouts.


**Additional Context:**
Use these beads commands to get more information if needed:
- `bd show {{item_id}} --json` - View full item details
- `bd list --deps {{item_id}} --json` - Check dependencies
- `bd list --label <label> --json` - Find related items by label

{{#mcp_enabled}}
**MCP Server Testing:**
If this work item involves modifying the MCP Server:
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

**IMPORTANT: Always use the `Invoke-MCPTool.ps1` script.**
Do not try to construct raw HTTP requests (Invoke-RestMethod) or use other clients. The script handles:
- Correct JSON-RPC 2.0 formatting
- Session headers and SSE connection details
- Output parsing and error handling

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
{{/mcp_enabled}}

{{#test_data_section}}
## Test data

{{test_data_section}}
{{/test_data_section}}

**Success Criteria:**
- Provided item is fully implemented
{{#mcp_enabled}}
- If MCP tools were modified, they have been tested manually and work correctly
{{/mcp_enabled}}
- All pre-commit validation passes successfully
- All changes are committed and the worktree has been merged

## If it is already completed

- Ensure all changes are committed and pushed.
- Do NOT run `bd close` or `bd update` — the orchestrator owns beads lifecycle.

## When you finish it

- Ensure all changes are committed and pushed so the orchestrator can merge.
- Do NOT run `bd close` or `bd update`.

## REQUIRED: Structured Outcome Report

**At the very end of your session**, you MUST output a structured JSON outcome block.
This tells the orchestrator what happened so it can make intelligent decisions.

Choose the appropriate status and fill in the fields:

### If you completed the work successfully:
```json
{
  "status": "completed",
  "reason": "Brief summary of what was done",
  "files_modified": ["src/file1.py", "src/file2.py"],
  "tests_added": ["tests/test_file1.py"],
  "suggested_split": []
}
```

### If the item is too large or too vague to complete:
```json
{
  "status": "too_large",
  "reason": "Why this item cannot be completed as-is",
  "files_modified": [],
  "tests_added": [],
  "suggested_split": ["Suggested sub-task 1", "Suggested sub-task 2"]
}
```

### If you are blocked on a dependency or missing information:
```json
{
  "status": "blocked",
  "reason": "What you need that you cannot find",
  "files_modified": [],
  "tests_added": [],
  "suggested_split": []
}
```

### If the requirements are unclear and you need clarification:
```json
{
  "status": "needs_clarification",
  "reason": "What specific questions need answering",
  "files_modified": [],
  "tests_added": [],
  "suggested_split": []
}
```

**Rules:**
- Always output exactly ONE outcome block at the END of your session
- The JSON must be in a fenced code block with the `json` language tag
- `status` must be one of: `completed`, `blocked`, `needs_clarification`, `too_large`
- `files_modified` and `tests_added` should list actual file paths you changed
- `suggested_split` is only relevant for `too_large` status
- If you completed the work, list ALL files you modified and tests you added
