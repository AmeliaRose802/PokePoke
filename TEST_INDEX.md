# list_kusto_queries MCP Tool - Test Index

## Overview
This directory contains comprehensive test results for the `list_kusto_queries` MCP tool, conducted on 2026-01-23.

## Test Results: ✓ ALL TESTS PASSED (13/13 - 100%)

---

## Document Guide

### 📊 Quick Start
**→ KUSTO_QUERIES_TEST_SUMMARY.md**
- 1-page quick reference
- Test statistics table
- All 19 query templates listed
- Key findings and recommendations
- **Read this first for overview**

### 📄 Detailed Analysis
**→ LIST_KUSTO_QUERIES_TEST_REPORT.md**
- Complete test report (~14KB)
- Detailed findings and analysis
- Harsh critique section
- Comprehensive improvement suggestions
- All 19 queries with full descriptions
- **Read this for in-depth understanding**

### 🔬 Test Case Documentation
**→ TEST_CASE_DETAILS.md**
- Individual test case details
- Exact parameters and responses for each test
- Complete query catalog with metadata
- Assessment and recommendations
- **Read this for test reproduction**

### 📝 Raw Output
**→ list_kusto_queries_test_results.txt**
- Raw console output from test run
- Unprocessed JSON responses
- Useful for debugging or verification

### 💻 Test Scripts
**→ test_kusto_queries_v2.cjs**
- Node.js test harness used
- Reusable for regression testing
- MCP client implementation

---

## Test Summary

| Metric | Value |
|--------|-------|
| Total Tests | 13 |
| Passed | 13 (100%) |
| Failed | 0 (0%) |
| Avg Response Time | 160ms |
| Queries Found | 19 |
| Categories | 2 (node, resolution) |

---

## Test Cases Executed

1. **No parameters** - List all queries (✓ 19 found)
2. **Category: performance** - (✓ 0 found - category doesn't exist)
3. **Category: error** - (✓ 0 found - category doesn't exist)
4. **Category: security** - (✓ 0 found - category doesn't exist)
5. **Category: diagnostics** - (✓ 0 found - category doesn't exist)
6. **Category: troubleshooting** - (✓ 0 found - category doesn't exist)
7. **Search: error** - (✓ 0 found)
8. **Search: performance** - (✓ 0 found)
9. **Search: security** - (✓ 0 found)
10. **Search: latency** - (✓ 0 found)
11. **Search: failure** - (✓ 0 found)
12. **Combined: category=performance, search=latency** - (✓ 0 found)
13. **Combined: category=error, search=failure** - (✓ 0 found)

---

## Key Findings

### ✓ Strengths
- 100% test stability
- Fast response times (89-334ms)
- Well-structured metadata
- Comprehensive Azure infrastructure coverage
- Multiple resolution strategies

### ⚠ Issues
- **Category mismatch**: Documentation vs. reality
- **Search ineffective**: Common terms return nothing
- **Limited scope**: 63% resolution queries
- **No query text**: Only metadata returned
- **Missing indicators**: No complexity/time estimates

---

## Overall Assessment

**Rating: 6.4/10**
- Stability: 10/10
- Functionality: 6/10
- Coverage: 5/10
- Usability: 4/10
- Incident Value: 7/10

**Verdict: CONDITIONALLY RECOMMENDED**

Use for Azure infrastructure incidents, avoid for general diagnostics.

---

## 19 Available Queries

### NODE (7)
- imds_heartbeat
- imds_successful_requests
- imds_version
- node_snapshot
- wireserver_heartbeat
- wireserver_successful_requests
- wireserver_version

### RESOLUTION (12)
- resolve_arm_resourceid_to_nodeid
- resolve_arm_to_container_guestagent
- resolve_arm_to_container_imds
- resolve_containerid_to_nodeid_wireserver
- resolve_containerid_to_nodeid_wireserver_precise
- resolve_containerid_via_guestagent
- resolve_correlationid_to_nodeid
- resolve_subscriptionid_to_nodeid
- resolve_tenantid_to_nodeid
- resolve_vmid_to_nodeid_imds
- resolve_vmid_via_attest
- resolve_vmid_via_guestagent

---

## Test Environment

- **Server**: IcmMcpServer v1.0.0.0
- **Protocol**: JSON-RPC 2.0 over stdio
- **Client**: Node.js with custom MCP client
- **Test Date**: 2026-01-23T23:43:21Z
- **Duration**: ~3 seconds (after 15s server startup)

---

## Reproduction

To reproduce these tests:
```bash
node test_kusto_queries_v2.cjs
```

Prerequisites:
- Node.js installed
- MCP server at: c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1
- ~15 seconds for server build and startup

---

*Testing completed by Beta Test Agent*
*Methodology: Comprehensive functional testing with edge cases*
*Approach: Constructively critical assessment*
