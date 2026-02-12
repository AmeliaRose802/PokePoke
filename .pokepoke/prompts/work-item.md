You are working on a beads work item. Please complete the following task:

**Work Item ID:** {{id}}
**Title:** {{title}}
**Description:**
{{description}}

**Priority:** {{priority}}
**Type:** {{issue_type}}{{#labels}}
**Labels:** {{labels}}{{/labels}}

**MCP Server Development:**
If this work item involves modifying the ICM MCP Server or using MCP tools:
1. **Restarting:** Always use `rmcp` or `.\scripts\Restart-MCPServer.ps1` after code changes.
2. **Testing Tools:** Always use `.\scripts\Invoke-MCPTool.ps1` to test tools.
   - Example: `.\scripts\Invoke-MCPTool.ps1 -Tool "tool_name" -Params @{arg="val"}`

🤖 **AUTONOMOUS MODE: NEVER ASK FOR PERMISSION**
- You are operating autonomously - proceed directly with implementation
- NEVER ask "Would you like me to proceed?" or "Should I continue?"
- NEVER wait for confirmation before fixing issues
- If you identify a problem, FIX IT IMMEDIATELY
- If you see a clear solution, IMPLEMENT IT IMMEDIATELY

Please implement this task according to the project guidelines and best practices. Make sure to:
1. Follow the coding standards
2. Add appropriate tests
3. Update documentation if needed
4. Commit your code changes with a descriptive message
5. Update beads items as needed - beads changes sync automatically via 'bd sync'
6. When done and all validation passes, merge your worktree to the default development branch and close your worktree

Work independently and autonomously. Report completion when done.

