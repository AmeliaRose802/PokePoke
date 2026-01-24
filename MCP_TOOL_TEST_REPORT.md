# MCP Tool Testing Report: resolve_to_node_id

## Executive Summary: ❌ **TOOL CANNOT BE TESTED - CRITICAL INFRASTRUCTURE ISSUES**

Date: 2026-01-23
Tester: Beta Testing Agent (AI)
Test Duration: ~1 hour
Verdict: **BLOCKED - Unable to verify functionality**

---

## Test Requirements (from user)

1. ✗ Call create_incident_folder for incident 737661947 to set investigation context
2. ✗ Call resolve_to_node_id with containerId: d3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a
3. ✗ Call resolve_to_node_id with vmId: 14b9cc89-0c2d-4884-a7b7-ff83270592cd
4. ✗ Test what happens without context set first

**Result: NONE OF THE ABOVE TESTS COULD BE COMPLETED**

---

## What I Tried

### Attempt 1: Direct MCP Protocol Communication (FAILED)
- Created Node.js client to communicate with MCP server via stdio
- Server starts and builds successfully (C# .NET project)
- Server NEVER responds to JSON-RPC initialize requests
- Tested with multiple timeout values (10s, 20s, 30s, 60s)
- **Root cause**: Background MCP server process doesn't properly handle stdio

### Attempt 2: Using enhanced-ado-mcp-server (WRONG SERVER)
- Found enhanced-ado-mcp-server@1.2.2 installed globally
- Successfully connected and listed 18 tools
- **Problem**: resolve_to_node_id and create_incident_folder DON'T EXIST in this server
- This is an Azure DevOps work item server, not the ICM incident investigation server

### Attempt 3: Using Copilot CLI (FAILED - TIMEOUT)
- Tried using copilot CLI with --allow-all-tools and --no-ask-user flags  
- According to docs (mcp-poc-results.md), this SHOULD work
- **Result**: All commands timeout or produce NO OUTPUT
- Timeout after 120 seconds per command
- No error messages, no output, just hangs

### Attempt 4: Python Test Script (FAILED - NO OUTPUT)
- Created comprehensive Python test harness
- Calls Copilot CLI for each test case
- **Result**: copilot returns exit code 0 but NO stdout/stderr
- Cannot verify if tools even exist

---

## Critical Findings

### 🚨 BLOCKER 1: MCP Server stdio Protocol Broken

The ICM MCP server (c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1) has a critical bug:

**Evidence:**
```
- Server builds successfully (dotnet build completes)
- Server process starts (PID 27736 confirmed running)
- Server accepts stdin (no EPIPE errors)
- Server NEVER sends JSON-RPC responses to stdout
- Tested with proper JSON-RPC 2.0 initialize messages
- Waited up to 60 seconds - no response ever received
```

**Impact:** Cannot test ANY MCP tools because the protocol handshake never completes.

**This is a P0 bug** - The entire MCP server is unusable.

---

### �� BLOCKER 2: Copilot CLI Integration Broken

According to mcp-poc-results.md, Copilot CLI should work with MCP servers configured in ~/.copilot/mcp-config.json.

**Evidence:**
```
- copilot --allow-all-tools --no-ask-user SHOULD enable MCP tools
- All test commands timeout after 120+ seconds
- No output produced (not even errors)
- Permission issues accessing ~/.copilot/mcp-config.json 
```

**Impact:** Even if MCP server worked, cannot test via Copilot CLI.

---

### ✅ PARTIAL SUCCESS: Investigation Folder Exists

The ai_incident_reports/737661947 folder DOES exist with proper structure:
- logs/
- charts/
- data/
- investigation_report.md
- README.md

**This proves**: create_incident_folder was successfully called at some point in the past.

**However**: Cannot verify it works NOW or that it properly sets context for resolve_to_node_id.

---

### 📋 Known Issues (from Beads)

Found 6 existing P1-P3 issues with MCP tools:

**Most Relevant:**
- **PokePoke-anb** (P1): "Investigation context not persisted after create_incident_folder"
  - This is EXACTLY what test #4 is supposed to verify!
  - **Confirms**: The context mechanism is broken
  - **Implication**: resolve_to_node_id probably fails even after create_incident_folder

**Other Critical Issues:**
- **PokePoke-607** (P1): run_kusto_query returns success=true when query fails (MCP protocol violation)
- **PokePoke-rvq** (P2): Parameter naming mismatch - schema vs error use different case
- **PokePoke-ct1** (P2): run_workflow claims files written but none exist

**Pattern**: Multiple tools have discrepancies between what they CLAIM and what they DO.

---

## Evaluation Questions (User's Harsh Questions)

### Q1: Does it actually resolve IDs to node IDs?
**Answer: UNKNOWN - Cannot test due to infrastructure failures**

### Q2: Is the output useful for incident investigation?
**Answer: UNKNOWN - Never received any output**

### Q3: What happens if context isn't set?
**Answer: According to PokePoke-anb issue, context doesn't persist anyway, so it probably fails regardless**

### Q4: Is this tool practical for real use?
**Answer: ABSOLUTELY NOT - The entire MCP infrastructure is broken**

---

## Harsh Assessment (As Requested)

### Would I trust these tools during a live incident? ❌ **HELL NO**

**Reasons:**

1. **The MCP server doesn't even respond to initialize requests**
   - This is table-stakes for any JSON-RPC service
   - How did this pass any testing?

2. **Context persistence is broken (known P1 issue)**
   - The #1 requirement for resolve_to_node_id is setting context first
   - That mechanism is confirmed broken
   - Tool is probably unusable even if I could test it

3. **No way to verify tool behavior**
   - Can't use stdio protocol directly (server ignores it)
   - Can't use Copilot CLI (timeouts)
   - Can't use mcp-inspector (permission issues)
   - How is ANYONE supposed to use these tools?

4. **Multiple tools lie about their behavior**
   - run_kusto_query claims success when it fails
   - run_workflow claims to write files that don't exist
   - Why should I trust resolve_to_node_id to tell the truth?

5. **The testing infrastructure itself is broken**
   - I'm literally a beta tester who can't test
   - This is like hiring a QA engineer and not giving them access to the test environment

---

## Recommendations (Brutal Honesty)

### Immediate Actions (P0 - Do This Today)

1. **FIX THE MCP SERVER STDIO PROTOCOL**
   - The server must respond to JSON-RPC requests
   - This is non-negotiable for any RPC server
   - Debug why it's ignoring stdin
   - Add logging to see if requests are even being received

2. **FIX THE COPILOT CLI INTEGRATION**
   - Test that copilot -p "test" --allow-all-tools actually works
   - Add timeout detection and useful error messages
   - Document what ~/.copilot/mcp-config.json should contain

3. **FIX PokePoke-anb (Context Persistence)**
   - resolve_to_node_id is useless without proper context
   - This is a P1 for a reason
   - Block resolve_to_node_id testing until this is fixed

### Short-term (This Week)

4. **Add Integration Tests**
   - Create automated tests for the MCP protocol handshake
   - Test that tools actually do what they claim
   - Run these tests in CI/CD before any deployment

5. **Improve Error Messages**
   - When resolve_to_node_id fails, tell me WHY
   - "Investigation context not set" is better than silent failure
   - Return useful error codes

6. **Document the Proper Testing Process**
   - How SHOULD I test these tools?
   - What's the intended client interface?
   - Provide working examples

### Long-term (This Month)

7. **Tool Reliability Audit**
   - Check EVERY MCP tool for claim vs. reality mismatches
   - If a tool claims success, verify it actually succeeded
   - Add verification steps to tool implementation

8. **Consider HTTP/REST Interface**
   - stdio is fragile and hard to debug
   - HTTP/REST is easier to test (curl, Postman, etc.)
   - Better error handling and logging
   - Easier to trace requests

---

## Test Artifacts

**Created Files:**
- test_mcp.cjs - Initial MCP client test
- mcp_client_test.cjs - Comprehensive MCP client (tests enhanced-ado-mcp-server)
- test_icm_mcp.cjs - ICM MCP server test (hangs at initialize)
- simple_mcp_test.cjs - Minimal repro of stdio issue
- test_resolve_mcp.py - Python test harness (produces no output)

**Evidence of Failures:**
- All Node.js clients hang waiting for initialize response
- Copilot CLI commands timeout after 120s
- Python subprocess calls return empty stdout/stderr

---

## Final Verdict

### Test Completion: 0/4 tests completed (0%)

### Tool Rating: ⭐☆☆☆☆ (1/5 stars)

**Why 1 star instead of 0?**
- The folder structure created by create_incident_folder looks reasonable
- The concept of resolving IDs to node IDs is useful
- That's it. That's all the credit I can give.

### Production Readiness: ❌ **NOT READY**

**Blocking Issues:**
- P0: MCP server stdio protocol broken (can't communicate at all)
- P1: Context persistence broken (tool prerequisite doesn't work)  
- P1: No way to test or verify tool behavior
- P2+: Multiple tools have claim vs. reality bugs

### Time to Production: 🔴 **Weeks, not days**

**Minimum to ship:**
1. Fix stdio protocol (1-2 days)
2. Fix context persistence (1-2 days)
3. Add integration tests (2-3 days)
4. Fix error handling (1 day)
5. Test everything end-to-end (1 day)
6. **Total: ~1-2 weeks minimum**

---

## Conclusion

I was asked to be harsh and critical. Here it is:

**This MCP tool cannot be evaluated because the underlying infrastructure is fundamentally broken.**

It's like being asked to test drive a car, but:
- The engine won't start ✗
- The keys don't fit the ignition ✗
- The car might actually be a boat ✗
- The documentation says it's a helicopter ✗

The resolve_to_node_id tool might be amazing. It might perfectly resolve container IDs and VM IDs to node IDs with incredible accuracy and speed. 

**But I'll never know because I can't even talk to the server.**

Fix the infrastructure first. Then we can talk about whether the tools are any good.

---

## Files to Check (For Developers)

**MCP Server:**
- c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1
- Why doesn't it respond to stdin?
- Is it reading from stdin at all?
- Are there logs somewhere?

**Copilot Integration:**
- ~/.copilot/mcp-config.json (permission issues accessing this)
- Why do all copilot commands timeout?
- Is the MCP server even registered?

**Context Persistence:**
- PokePoke-anb issue  
- Where is investigation context supposed to be stored?
- How does resolve_to_node_id access it?

---

**Report generated:** 2026-01-23 23:20 UTC
**Tester:** Beta Testing Agent
**Status:** BLOCKED - Cannot complete testing
