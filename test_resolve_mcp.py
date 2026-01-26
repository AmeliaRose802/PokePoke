#!/usr/bin/env python3
"""
Comprehensive test of resolve_to_node_id MCP tool.
Tests requirements from beta-tester prompt.
"""
import subprocess
import json
import sys
from pathlib import Path

class MCPToolTester:
    def __init__(self):
        self.results = []
        
    def run_copilot_with_mcp(self, prompt):
        """Run a command via Copilot CLI with MCP support."""
        try:
            result = subprocess.run(
                ['copilot', '-p', prompt, '--allow-all-tools', '--no-ask-user'],
                capture_output=True,
                text=True,
                timeout=120
            )
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'error': 'Command timed out after 120 seconds'}
        except Exception as e:
            return {'error': str(e)}
    
    def test_1_without_context(self):
        """TEST 1: Call resolve_to_node_id WITHOUT setting context first."""
        print("\n" + "="*80)
        print("TEST 1: resolve_to_node_id WITHOUT context (should fail)")
        print("="*80)
        
        prompt = "Call MCP tool resolve_to_node_id with containerId d3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a and incidentTime 2026-01-23T20:14:55.9797441Z without creating incident folder. Report what happens."
        
        result = self.run_copilot_with_mcp(prompt)
        print(f"Output:\n{result.get('stdout', 'NO OUTPUT')[:500]}")
        
        self.results.append({'test': '1_without_context', 'result': result})
    
    def test_2_create_context(self):
        """TEST 2: Create incident folder."""
        print("\n" + "="*80)
        print("TEST 2: create_incident_folder for incident 737661947")
        print("="*80)
        
        prompt = "Call MCP tool create_incident_folder with incident_id 737661947. Verify folder was created."
        
        result = self.run_copilot_with_mcp(prompt)
        print(f"Output:\n{result.get('stdout', 'NO OUTPUT')[:500]}")
        
        folder = Path("ai_incident_reports/737661947")
        print(f"\nFolder exists: {folder.exists()}")
        
        self.results.append({'test': '2_create_context', 'folder_exists': folder.exists()})
    
    def test_3_with_container(self):
        """TEST 3: With containerId after context."""
        print("\n" + "="*80)
        print("TEST 3: resolve_to_node_id WITH containerId (after context)")
        print("="*80)
        
        prompt = "Call MCP tool resolve_to_node_id with containerId d3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a and incidentTime 2026-01-23T20:14:55.9797441Z. Report node ID returned."
        
        result = self.run_copilot_with_mcp(prompt)
        print(f"Output:\n{result.get('stdout', 'NO OUTPUT')[:500]}")
        
        self.results.append({'test': '3_with_container'})
    
    def test_4_with_vm(self):
        """TEST 4: With vmId."""
        print("\n" + "="*80)
        print("TEST 4: resolve_to_node_id WITH vmId")
        print("="*80)
        
        prompt = "Call MCP tool resolve_to_node_id with vmId 14b9cc89-0c2d-4884-a7b7-ff83270592cd and incidentTime 2026-01-23T20:14:55.9797441Z."
        
        result = self.run_copilot_with_mcp(prompt)
        print(f"Output:\n{result.get('stdout', 'NO OUTPUT')[:500]}")
        
        self.results.append({'test': '4_with_vm'})

def main():
    print("MCP resolve_to_node_id Testing")
    
    tester = MCPToolTester()
    tester.test_1_without_context()
    tester.test_2_create_context()
    tester.test_3_with_container()
    tester.test_4_with_vm()
    
    print("\n" + "="*80)
    print("Tests complete")
    print("="*80)

if __name__ == '__main__':
    main()
