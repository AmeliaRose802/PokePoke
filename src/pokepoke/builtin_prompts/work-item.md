You are working on a beads work item. Please complete the following task:

**Work Item ID:** {{id}}
**Title:** {{title}}
**Description:**
{{description}}

**Priority:** {{priority}}
**Type:** {{issue_type}}{{#labels}}
**Labels:** {{labels}}{{/labels}}

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
5. When done and all validation passes, push your commits — the orchestrator handles merging and closing
6. Do NOT run `bd close` or `bd update` — the orchestrator owns beads lifecycle

Work independently and autonomously. Report completion when done.

## Avoiding Hung Commands

**Command Timeout: {{command_timeout}} seconds**

1. **Always use timeouts for pytest:**
   ```powershell
   pytest --timeout={{command_timeout}}
   ```
2. **For targeted tests, still use --timeout:**
   ```powershell
   pytest tests/test_specific_module.py --timeout={{command_timeout}}
   ```
3. **NEVER use Select-Object -First/-Last:**
   These flags can hang PowerShell pipelines. Use safe alternatives instead:
   ```powershell
   Get-Content file.txt -Head 10
   Get-Content file.txt -Tail 5
   $lines = Get-Content file.txt
   $lines[0..9]
   ```
4. **If a command appears stuck:**
   - After 2-3 `read_powershell` calls with no new output, the command is likely hung
   - Use `stop_powershell` to kill the hung process
   - Retry with a timeout flag or run targeted tests instead
5. **When writing tests that touch subprocess/git/filesystem:**
   Use mocks or explicit timeouts. Avoid integration tests that run real operations without timeouts.

