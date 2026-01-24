#!/usr/bin/env pwsh
# Test script for MCP Bridge

Import-Module "$PSScriptRoot\MCPBridge.psm1" -Force -Verbose

Write-Host "`n=== Testing MCP Bridge ===" -ForegroundColor Cyan

# Test 1: List tools
Write-Host "`n[Test 1] Listing MCP tools..." -ForegroundColor Yellow
Get-MCPTools

# Cleanup
Stop-MCPServerProcess

Write-Host "`n=== Tests Complete ===" -ForegroundColor Green
