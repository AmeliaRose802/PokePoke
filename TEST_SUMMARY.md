# resolve_to_node_id MCP Tool - Test Summary

## Status: ❌ FAILED TO TEST (Infrastructure Broken)

### Tests Required
- [❌] Test 1: resolve_to_node_id WITHOUT context
- [❌] Test 2: create_incident_folder to set context  
- [❌] Test 3: resolve_to_node_id WITH containerId
- [❌] Test 4: resolve_to_node_id WITH vmId

**Completion: 0/4 (0%)**

### Why Testing Failed

The MCP server has a critical bug where it:
1. ✅ Builds successfully (dotnet build works)
2. ✅ Starts successfully (process running)
3. ❌ **Never responds to JSON-RPC requests over stdio**

This makes the entire MCP infrastructure unusable for testing.

### Issues Filed

**NEW:**
- **PokePoke-twk** (P0): MCP server stdio protocol non-responsive

**EXISTING (Related):**
- **PokePoke-anb** (P1): Investigation context not persisted after create_incident_folder
- **PokePoke-607** (P1): run_kusto_query returns success=true even when query fails

### Rating

**1/5 stars** ⭐☆☆☆☆

The 1 star is for:
- The folder structure from create_incident_folder looks reasonable
- The concept of ID resolution is useful
- That's it

### Would I Use This in Production?

**NO.** Not until:
1. The stdio protocol works (P0)
2. Context persistence works (P1)
3. Integration tests prove reliability
4. Error messages are useful

### Time to Fix

Estimated **1-2 weeks minimum** to make this functional.

### Artifacts Created

Testing code:
- test_mcp.cjs
- mcp_client_test.cjs  
- test_icm_mcp.cjs
- simple_mcp_test.cjs
- test_resolve_mcp.py

Documentation:
- MCP_TOOL_TEST_REPORT.md (full details)
- This summary

### Key Learnings

1. **Background MCP servers are problematic**
   - stdio protocol requires active communication
   - Background processes don't handle it properly
   
2. **Copilot CLI integration is broken**
   - Commands timeout with no output
   - No useful error messages
   
3. **Multiple tools have claim vs. reality bugs**
   - Tools report success when they fail
   - Tools claim to create files that don't exist
   
4. **Testing infrastructure needs work**
   - No easy way to verify MCP tool behavior
   - Need integration tests in CI/CD
   - Need better logging and diagnostics

### Recommendation

**STOP** adding new MCP tools until the infrastructure is fixed.

**FOCUS** on:
1. Making stdio protocol work
2. Adding integration tests
3. Fixing existing P1 issues
4. Improving error handling

---

**Report Date:** 2026-01-23
**Tester:** Beta Testing Agent (AI)
**Test Status:** BLOCKED
