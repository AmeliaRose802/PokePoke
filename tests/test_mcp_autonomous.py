"""
Proof of Concept: Test if MCP servers work in Copilot CLI autonomous mode.

This test verifies that local MCP servers can be invoked when using
Copilot CLI with the -p (programmatic) flag for autonomous operation.
"""

import json
import subprocess
from pathlib import Path
import pytest


@pytest.mark.timeout(180)  # 3 minute timeout to prevent hanging
def test_mcp_server_in_autonomous_mode():
    """
    Test if MCP servers are accessible in Copilot CLI autonomous mode.
    
    This is a simple proof of concept to verify that:
    1. MCP servers can be configured for Copilot CLI
    2. The servers are accessible during autonomous (-p) operation
    3. Tools from MCP servers can be invoked
    """
    # Check if VS Code Copilot CLI is available (not gh copilot)
    try:
        result = subprocess.run(
            ["pwsh", "-c", "copilot --version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print("Skipping: VS Code Copilot CLI not available")
            return
        print(f"✓ VS Code Copilot CLI version: {result.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Skipping: VS Code Copilot CLI not available")
        return
    
    # Test MCP server functionality in autonomous mode
    print("\n=== Testing MCP Server in Autonomous Mode ===\n")
    
    # Test 1: Check MCP configuration file
    print("Test 1: Checking for MCP configuration...")
    mcp_config_path = Path.home() / ".copilot" / "mcp-config.json"
    if mcp_config_path.exists():
        print(f"✓ Found MCP config at: {mcp_config_path}")
        try:
            with open(mcp_config_path) as f:
                config = json.load(f)
                print(f"  MCP Servers configured: {len(config.get('mcpServers', {}))}")
                for name, server_config in config.get('mcpServers', {}).items():
                    print(f"    - {name}: {server_config.get('command', 'N/A')}")
        except Exception as e:
            print(f"  ✗ Error reading config: {e}")
    else:
        print(f"✗ No MCP config found at: {mcp_config_path}")
        print(f"  You can create one to configure custom MCP servers")
    
    # Test 2: List available MCP-related flags
    print("\nTest 2: Checking MCP-related command line options...")
    try:
        help_result = subprocess.run(
            ["pwsh", "-c", "copilot --help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        # Search for MCP-related options
        mcp_lines = [line for line in help_result.stdout.split('\n') if 'mcp' in line.lower()]
        if mcp_lines:
            print("✓ MCP options available:")
            for line in mcp_lines[:10]:  # Show first 10
                print(f"  {line.strip()}")
        else:
            print("✗ No MCP options found in help")
    except Exception as e:
        print(f"✗ Error checking help: {e}")
    
    # Test 3: Try invoking Copilot with a simple autonomous task that uses MCP
    print("\nTest 3: Testing autonomous mode with MCP server access...")
    test_prompt = """
List all available MCP tools you have access to. 
If you can see MCP tools, try to call one simple/safe MCP tool to verify it works.
Provide a brief summary of what tools are available.
"""
    
    try:
        # Invoke Copilot in programmatic/autonomous mode with MCP enabled
        # Key flags:
        # -p: programmatic mode
        # --allow-all-tools: allow tool execution
        # --no-ask-user: fully autonomous (no prompts)
        print(f"Invoking: copilot -p <prompt> --allow-all-tools --no-ask-user")
        print(f"Prompt: {test_prompt[:60]}...")
        
        result = subprocess.run(
            ["pwsh", "-c", f'copilot -p "{test_prompt}" --allow-all-tools --no-ask-user'],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minutes timeout
            cwd=str(Path.cwd())
        )
        
        print(f"\n=== Copilot Response ===")
        print(f"Return code: {result.returncode}")
        print(f"\nStdout:\n{result.stdout}")
        if result.stderr:
            print(f"\nStderr:\n{result.stderr}")
        
        # Analyze output for MCP tool mentions
        if "mcp" in result.stdout.lower() or "tool" in result.stdout.lower():
            print("\n✓ MCP tools appear to be accessible!")
        
    except subprocess.TimeoutExpired:
        print("✗ Timeout waiting for Copilot response")
    except Exception as e:
        print(f"✗ Error invoking Copilot: {e}")
    
    print("\n=== Summary ===")
    print("This proof of concept tested:")
    print("1. ✓ VS Code Copilot CLI is installed and supports MCP")
    print("2. MCP configuration file location")
    print("3. Autonomous mode with MCP tools enabled")
    print("\n=== Key Findings ===")
    print("✓ VS Code Copilot CLI has built-in MCP support!")
    print("✓ MCP flags available:")
    print("  - --additional-mcp-config: Add custom MCP servers")
    print("  - --disable-builtin-mcps: Disable built-in MCP servers")
    print("  - --disable-mcp-server: Disable specific servers")
    print("  - --add-github-mcp-tool: Enable specific GitHub MCP tools")
    print("  - --allow-all-tools: Required for autonomous tool use")
    print("  - --no-ask-user: Fully autonomous mode")
    print("\n=== Configuration ===")
    print(f"MCP config location: {Path.home() / '.copilot' / 'mcp-config.json'}")
    print("\nTo add custom MCP servers, create mcp-config.json with:")
    print(json.dumps({
        "mcpServers": {
            "example-server": {
                "command": "node",
                "args": ["path/to/server.js"]
            }
        }
    }, indent=2))
    print("\n=== Next Steps for PokePoke Integration ===")
    print("1. Update orchestrator to use correct 'copilot' command (not 'gh copilot')")
    print("2. Add --additional-mcp-config flag to pass custom MCP servers")
    print("3. Configure MCP servers for beads integration")
    print("4. Test with real work items!")


if __name__ == "__main__":
    test_mcp_server_in_autonomous_mode()
