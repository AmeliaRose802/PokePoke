const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

class ICMMCPClient {
    constructor() {
        this.messageId = 0;
        this.pendingRequests = new Map();
        this.initialized = false;
        this.serverPath = 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1';
    }

    async start() {
        return new Promise((resolve, reject) => {
            console.log(`Starting MCP server from: ${this.serverPath}`);
            
            this.server = spawn('pwsh', [
                '-NoProfile',
                '-ExecutionPolicy', 'Bypass',
                '-File', this.serverPath
            ], {
                stdio: ['pipe', 'pipe', 'pipe']
            });

            this.rl = readline.createInterface({
                input: this.server.stdout,
                crlfDelay: Infinity
            });

            let lineCount = 0;
            this.rl.on('line', (line) => {
                lineCount++;
                
                // Skip build/compilation output
                if (line.includes('Build succeeded') || line.includes('Time Elapsed') || 
                    line.includes('Building') || line.includes('Copying') || 
                    line.includes('Workload updates') || !line.trim()) {
                    return;
                }

                try {
                    const msg = JSON.parse(line);
                    this.handleMessage(msg);
                } catch (e) {
                    // Not JSON - might be a log line
                    if (line.includes('[INFO]') || line.includes('[ERROR]') || line.includes('[DEBUG]')) {
                        console.log('LOG:', line);
                    }
                }
            });

            this.server.stderr.on('data', (data) => {
                const str = data.toString();
                if (str.includes('[INFO]') || str.includes('[ERROR]')) {
                    console.error('STDERR:', str);
                }
            });

            this.server.on('error', (err) => {
                console.error('Server process error:', err);
                reject(err);
            });

            // Wait for server to start (it needs to build first)
            console.log('Waiting for server to build and start (10 seconds)...');
            setTimeout(resolve, 10000);
        });
    }

    handleMessage(msg) {
        if (msg.id && this.pendingRequests.has(msg.id)) {
            const { resolve, reject } = this.pendingRequests.get(msg.id);
            this.pendingRequests.delete(msg.id);
            
            if (msg.error) {
                reject(new Error(JSON.stringify(msg.error)));
            } else {
                resolve(msg.result);
            }
        }
    }

    sendRequest(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++this.messageId;
            const message = {
                jsonrpc: '2.0',
                id,
                method,
                params
            };

            this.pendingRequests.set(id, { resolve, reject });
            this.server.stdin.write(JSON.stringify(message) + '\n');

            // Timeout after 60 seconds (Kusto queries can be slow)
            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error(`Request timeout for ${method}`));
                }
            }, 60000);
        });
    }

    async initialize() {
        console.log('\n=== Initializing MCP connection ===');
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: {
                name: 'icm-test-client',
                version: '1.0.0'
            }
        });
        this.initialized = true;
        console.log('✓ Initialized successfully');
        console.log(`Server: ${result.serverInfo.name} v${result.serverInfo.version}`);
        return result;
    }

    async listTools() {
        console.log('\n=== Listing available tools ===');
        const result = await this.sendRequest('tools/list', {});
        return result;
    }

    async callTool(name, args) {
        console.log(`\n=== Calling tool: ${name} ===`);
        console.log(`Arguments: ${JSON.stringify(args, null, 2)}`);
        const result = await this.sendRequest('tools/call', {
            name,
            arguments: args
        });
        return result;
    }

    close() {
        if (this.server) {
            this.server.kill();
        }
    }
}

async function runTests() {
    const client = new ICMMCPClient();
    let exitCode = 0;
    
    try {
        await client.start();
        await client.initialize();
        
        // List tools
        const toolsResult = await client.listTools();
        console.log(`\n✓ Found ${toolsResult.tools.length} tools:`);
        toolsResult.tools.forEach((tool, i) => {
            console.log(`  ${i+1}. ${tool.name}`);
            console.log(`     ${tool.description.substring(0, 100)}...`);
        });

        // Check if resolve_to_node_id exists
        const resolveTool = toolsResult.tools.find(t => t.name === 'resolve_to_node_id');
        const contextTool = toolsResult.tools.find(t => t.name === 'create_incident_folder');
        
        console.log(`\n=== Checking for required tools ===`);
        console.log(`resolve_to_node_id: ${resolveTool ? '✓ FOUND' : '✗ MISSING'}`);
        console.log(`create_incident_folder: ${contextTool ? '✓ FOUND' : '✗ MISSING'}`);

        if (!resolveTool || !contextTool) {
            console.log('\n❌ CRITICAL: Required tools are missing!');
            exitCode = 1;
        } else {
            console.log('\n✓ All required tools are present');
            
            // Now run the actual tests as specified
            console.log('\n' + '='.repeat(80));
            console.log('TEST 1: Call resolve_to_node_id WITHOUT context (should fail)');
            console.log('='.repeat(80));
            try {
                const result1 = await client.callTool('resolve_to_node_id', {
                    containerId: 'd3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a',
                    incidentTime: '2026-01-23T20:14:55.9797441Z'
                });
                console.log('Result:', JSON.stringify(result1, null, 2));
            } catch (error) {
                console.log('❌ Error (expected):', error.message);
            }

            console.log('\n' + '='.repeat(80));
            console.log('TEST 2: Create incident folder for context');
            console.log('='.repeat(80));
            const contextResult = await client.callTool('create_incident_folder', {
                incident_id: '737661947'
            });
            console.log('Result:', JSON.stringify(contextResult, null, 2));

            console.log('\n' + '='.repeat(80));
            console.log('TEST 3: Call resolve_to_node_id WITH containerId');
            console.log('='.repeat(80));
            const result2 = await client.callTool('resolve_to_node_id', {
                containerId: 'd3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a',
                incidentTime: '2026-01-23T20:14:55.9797441Z'
            });
            console.log('Result:', JSON.stringify(result2, null, 2));

            console.log('\n' + '='.repeat(80));
            console.log('TEST 4: Call resolve_to_node_id WITH vmId');
            console.log('='.repeat(80));
            const result3 = await client.callTool('resolve_to_node_id', {
                vmId: '14b9cc89-0c2d-4884-a7b7-ff83270592cd',
                incidentTime: '2026-01-23T20:14:55.9797441Z'
            });
            console.log('Result:', JSON.stringify(result3, null, 2));
        }

    } catch (error) {
        console.error('\n❌ Test failed with error:', error.message);
        console.error(error.stack);
        exitCode = 1;
    } finally {
        console.log('\n' + '='.repeat(80));
        console.log('Cleaning up...');
        client.close();
        setTimeout(() => process.exit(exitCode), 1000);
    }
}

runTests();
