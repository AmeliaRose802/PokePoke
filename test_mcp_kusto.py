import json
import subprocess
import sys
import time

MCP_SERVER_PATH = r'c:\Users\ameliapayne\icm_queue_c#\start-mcp-server.ps1'

def send_jsonrpc_request(process, method, params=None):
    """Send a JSON-RPC request to the MCP server"""
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
    for i in range(50):
        line = process.stdout.readline()
        if not line:
            break
        line = line.strip()
        if line:
            try:
                response = json.loads(line)
                if response.get("jsonrpc") == "2.0" and ("result" in response or "error" in response):
                    return response
            except json.JSONDecodeError:
                # Skip non-JSON lines
                pass
    return None

print("=" * 70)
print("Testing check_kusto_health MCP Tool")
print("=" * 70)
print()

# Start MCP server
print("Starting MCP server...")
process = subprocess.Popen(
    ['pwsh', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', MCP_SERVER_PATH],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

# Wait for server to start
time.sleep(10)

try:
    # Initialize
    print("Initializing connection...")
    init_response = send_jsonrpc_request(process, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0.0"}
    })
    
    if init_response and init_response.get("result"):
        print("✓ Connected to MCP server\n")
        
        # List tools
        print("-" * 70)
        print("Listing available tools...")
        print("-" * 70)
        tools_response = send_jsonrpc_request(process, "tools/list")
        
        if tools_response and tools_response.get("result"):
            tools = tools_response["result"].get("tools", [])
            print(f"Found {len(tools)} tools:")
            for tool in tools:
                print(f"  • {tool['name']}")
                if tool.get('description'):
                    print(f"    {tool['description']}")
            
            # Find check_kusto_health
            kusto_tool = next((t for t in tools if t["name"] == "check_kusto_health"), None)
            if not kusto_tool:
                print("\n✗ ERROR: check_kusto_health tool not found!")
                sys.exit(1)
            
            print(f"\n✓ Found check_kusto_health tool")
            print(f"  Description: {kusto_tool.get('description', 'N/A')}")
            print(f"  Input Schema: {json.dumps(kusto_tool.get('inputSchema', {}), indent=2)}")
            
            # TEST 1: Default parameters
            print("\n" + "-" * 70)
            print("TEST 1: Call check_kusto_health with DEFAULT parameters")
            print("-" * 70)
            
            result1 = send_jsonrpc_request(process, "tools/call", {
                "name": "check_kusto_health",
                "arguments": {}
            })
            
            if result1:
                print("\n📊 Response Structure:")
                print(f"  Has result: {'result' in result1}")
                print(f"  Has error: {'error' in result1}")
                print("\n📄 Full Response:")
                print(json.dumps(result1, indent=2))
            
            # TEST 2: Explicit parameters
            print("\n" + "-" * 70)
            print("TEST 2: Call check_kusto_health with EXPLICIT parameters")
            print("Parameters: cluster='help.kusto.windows.net', database='Samples'")
            print("-" * 70)
            
            result2 = send_jsonrpc_request(process, "tools/call", {
                "name": "check_kusto_health",
                "arguments": {
                    "cluster": "help.kusto.windows.net",
                    "database": "Samples"
                }
            })
            
            if result2:
                print("\n📊 Response Structure:")
                print(f"  Has result: {'result' in result2}")
                print(f"  Has error: {'error' in result2}")
                print("\n📄 Full Response:")
                print(json.dumps(result2, indent=2))
            
            # Analysis
            print("\n" + "=" * 70)
            print("ANALYSIS")
            print("=" * 70)
            
            def get_text_content(result):
                if result and "result" in result:
                    content = result["result"].get("content", [])
                    for item in content:
                        if item.get("type") == "text":
                            return item.get("text", "")
                return ""
            
            text1 = get_text_content(result1)
            text2 = get_text_content(result2)
            
            print("\n1. Data Structure:")
            print("   - Both responses follow MCP content format")
            print(f"   - Result 1 has content: {bool(text1)}")
            print(f"   - Result 2 has content: {bool(text2)}")
            
            print("\n2. Response Comparison:")
            print(f"   Default params response: {text1}")
            print(f"   Explicit params response: {text2}")
            print(f"   Are they identical? {text1 == text2}")
            
            print("\n3. Health Metrics Assessment:")
            import re
            health_patterns = [
                r'status', r'healthy', r'available', r'response time',
                r'latency', r'error', r'warning', r'cpu', r'memory', r'connection'
            ]
            
            def has_metrics(text):
                return any(re.search(pattern, text, re.IGNORECASE) for pattern in health_patterns)
            
            has_metrics1 = has_metrics(text1)
            has_metrics2 = has_metrics(text2)
            
            print(f"   Test 1 contains health metrics: {has_metrics1}")
            print(f"   Test 2 contains health metrics: {has_metrics2}")
            
            print("\n4. Is this a dummy response?")
            dummy_patterns = [r'^ok$', r'^healthy$', r'mock', r'stub', r'placeholder', r'not implemented', r'todo']
            
            def is_dummy(text):
                return any(re.search(pattern, text.strip(), re.IGNORECASE) for pattern in dummy_patterns)
            
            dummy1 = is_dummy(text1)
            dummy2 = is_dummy(text2)
            
            print(f"   Test 1 appears to be dummy: {dummy1}")
            print(f"   Test 2 appears to be dummy: {dummy2}")
            
            print("\n5. Usefulness for Incident Investigation:")
            if has_metrics1 or has_metrics2:
                print("   ✓ USEFUL - Provides actual health metrics")
            else:
                print("   ✗ LIMITED USE - Missing key health metrics")
                if dummy1 or dummy2:
                    print("   ⚠ CRITICAL: Tool appears to return dummy/mock data")
            
            print("\n" + "=" * 70)
            print("TEST COMPLETE")
            print("=" * 70)
        else:
            print("✗ Failed to list tools")
            print(tools_response)
    else:
        print("✗ Failed to initialize")
        print(init_response)
        
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    process.terminate()
    process.wait(timeout=5)
