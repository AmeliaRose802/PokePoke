#!/usr/bin/env python3
"""
List all available MCP tools from the ICM MCP server.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

MCP_SERVER_PATH = r'c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1'
OUTPUT_FILE = 'mcp_tools_list.txt'

def send_jsonrpc_request(process, method, params=None, request_id=None):
    """Send a JSON-RPC request to the MCP server"""
    if request_id is None:
        request_id = int(time.time() * 1000)
    
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method
    }
    if params is not None:
        request["params"] = params
    
    request_json = json.dumps(request) + '\n'
    process.stdin.write(request_json)
    process.stdin.flush()
    
    # Read response - filter JSON lines
    max_attempts = 100
    for i in range(max_attempts):
        line = process.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        line = line.strip()
        if line:
            try:
                response = json.loads(line)
                if response.get("jsonrpc") == "2.0" and response.get("id") == request_id:
                    return response
            except json.JSONDecodeError:
                # Skip non-JSON lines (build output, logs, etc.)
                pass
    return None

def main():
    print("=" * 80)
    print("LISTING ALL AVAILABLE MCP TOOLS")
    print("=" * 80)
    print()
    
    # Start MCP server
    print("Starting MCP server (this will take ~10 seconds to build)...")
    process = subprocess.Popen(
        ['pwsh', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', MCP_SERVER_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    # Wait for server to build and start
    print("Waiting for server to build...")
    time.sleep(12)
    
    output_lines = []
    
    try:
        # Initialize
        print("Initializing connection...")
        init_response = send_jsonrpc_request(process, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tool-list-client", "version": "1.0.0"}
        }, request_id=1)
        
        if not init_response or not init_response.get("result"):
            print("✗ Failed to initialize connection")
            print(f"Response: {init_response}")
            sys.exit(1)
        
        server_info = init_response["result"].get("serverInfo", {})
        print(f"✓ Connected to: {server_info.get('name', 'Unknown')} v{server_info.get('version', 'Unknown')}")
        print()
        
        output_lines.append("=" * 80)
        output_lines.append("MCP TOOLS LIST")
        output_lines.append("=" * 80)
        output_lines.append("")
        
        # List tools
        print("Fetching tools list...")
        tools_response = send_jsonrpc_request(process, "tools/list", {}, request_id=2)
        
        if not tools_response or not tools_response.get("result"):
            print("✗ Failed to retrieve tools list")
            print(f"Response: {tools_response}")
            sys.exit(1)
        
        tools = tools_response["result"].get("tools", [])
        print(f"✓ Found {len(tools)} tools\n")
        
        output_lines.append(f"Total Tools: {len(tools)}")
        output_lines.append("")
        
        # Display each tool
        for index, tool in enumerate(tools, 1):
            tool_name = tool.get("name", "Unknown")
            tool_desc = tool.get("description", "No description available")
            
            # Console output
            print(f"{index}. {tool_name}")
            print(f"   Description: {tool_desc}")
            
            # File output
            output_lines.append(f"{index}. {tool_name}")
            output_lines.append(f"   Description: {tool_desc}")
            
            # Show parameters if available
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            
            if properties:
                print(f"   Parameters:")
                output_lines.append(f"   Parameters:")
                for param_name, param_info in properties.items():
                    is_required = param_name in required
                    req_mark = " (required)" if is_required else " (optional)"
                    param_type = param_info.get("type", "")
                    param_desc = param_info.get("description", "")
                    
                    param_line = f"     - {param_name}{req_mark}"
                    if param_type:
                        param_line += f" [{param_type}]"
                    if param_desc:
                        param_line += f": {param_desc}"
                    
                    print(param_line)
                    output_lines.append(param_line)
            
            print()
            output_lines.append("")
        
        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        output_lines.append("=" * 80)
        output_lines.append("SUMMARY")
        output_lines.append("=" * 80)
        output_lines.append("")
        
        # Check for specifically requested tools
        interested_tools = ['resolve_to_node_id', 'create_incident_folder']
        print("\nTools you specifically asked about:")
        output_lines.append("Tools specifically requested:")
        
        for tool_name in interested_tools:
            found = any(t.get("name") == tool_name for t in tools)
            mark = "✓" if found else "✗"
            status = "FOUND" if found else "NOT FOUND"
            line = f"  {mark} {tool_name}: {status}"
            print(line)
            output_lines.append(line)
        
        # Find incident investigation related tools
        print("\nTools related to incident investigation:")
        output_lines.append("")
        output_lines.append("Tools related to incident investigation:")
        
        investigation_keywords = [
            'incident', 'investigate', 'kusto', 'query', 'resolve',
            'node', 'health', 'check', 'folder', 'create', 'vm', 'container'
        ]
        
        investigation_tools = []
        for tool in tools:
            tool_name = tool.get("name", "").lower()
            tool_desc = tool.get("description", "").lower()
            
            if any(kw in tool_name or kw in tool_desc for kw in investigation_keywords):
                investigation_tools.append(tool.get("name"))
        
        if investigation_tools:
            for tool_name in investigation_tools:
                line = f"  • {tool_name}"
                print(line)
                output_lines.append(line)
        else:
            print("  (None found)")
            output_lines.append("  (None found)")
        
        print()
        print("=" * 80)
        output_lines.append("")
        output_lines.append("=" * 80)
        
        # Write to file
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        
        print(f"\n✓ Full tool list saved to: {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\nCleaning up...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except:
            process.kill()

if __name__ == '__main__':
    main()
