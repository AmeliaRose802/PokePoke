const { spawn } = require('child_process');
const readline = require('readline');

class MCPClient {
    constructor() {
        this.messageId = 0;
        this.pendingRequests = new Map();
        this.initialized = false;
    }

    async start() {
        return new Promise((resolve, reject) => {
            this.server = spawn('cmd.exe', [
                '/c', 'npx', 'enhanced-ado-mcp-server', 
                'msazure', 
                '--area-path', 'ICM\\Azure Data', 
                '--authentication', 'env'
            ], {
                stdio: ['pipe', 'pipe', 'pipe']
            });

            this.rl = readline.createInterface({
                input: this.server.stdout,
                crlfDelay: Infinity
            });

            this.rl.on('line', (line) => {
                if (!line.trim() || line.includes('pm exec') || line.includes(':\\Windows\\system32\\cmd.exe')) {
                    return;
                }

                try {
                    const msg = JSON.parse(line);
                    this.handleMessage(msg);
                } catch (e) {
                    // Not JSON - might be a log line
                    if (line.includes('[INFO]') || line.includes('[ERROR]')) {
                        // Ignore logs for now
                    }
                }
            });

            this.server.stderr.on('data', (data) => {
                // Suppress stderr logs
            });

            this.server.on('error', reject);

            // Wait for server to start
            setTimeout(resolve, 3000);
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

            // Timeout after 30 seconds
            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error('Request timeout'));
                }
            }, 30000);
        });
    }

    async initialize() {
        console.log('Initializing MCP connection...');
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: {
                name: 'test-client',
                version: '1.0.0'
            }
        });
        this.initialized = true;
        console.log('✓ Initialized successfully');
        return result;
    }

    async listTools() {
        console.log('\nListing available tools...');
        const result = await this.sendRequest('tools/list', {});
        return result;
    }

    async callTool(name, args) {
        console.log(`\nCalling tool: ${name}`);
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

async function main() {
    const client = new MCPClient();
    
    try {
        await client.start();
        await client.initialize();
        
        // List tools
        const toolsResult = await client.listTools();
        console.log(`\nFound ${toolsResult.tools.length} tools:`);
        toolsResult.tools.forEach(tool => {
            console.log(`  - ${tool.name}: ${tool.description}`);
        });

        // Find resolve_to_node_id tool
        const resolveTool = toolsResult.tools.find(t => t.name === 'resolve_to_node_id');
        if (resolveTool) {
            console.log(`\n✓ Found resolve_to_node_id tool`);
            console.log(`Schema: ${JSON.stringify(resolveTool.inputSchema, null, 2)}`);
        }

        console.log('\n\n=== TEST 1: Call resolve_to_node_id WITHOUT context (should fail) ===');
        try {
            const result1 = await client.callTool('resolve_to_node_id', {
                containerId: 'd3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a',
                incidentTime: '2026-01-23T20:14:55.9797441Z'
            });
            console.log('Result:', JSON.stringify(result1, null, 2));
        } catch (error) {
            console.log('❌ Error (expected):', error.message);
        }

        console.log('\n\n=== TEST 2: Create incident folder for context ===');
        const contextResult = await client.callTool('create_incident_folder', {
            incident_id: '737661947'
        });
        console.log('Result:', JSON.stringify(contextResult, null, 2));

        console.log('\n\n=== TEST 3: Call resolve_to_node_id WITH containerId ===');
        const result2 = await client.callTool('resolve_to_node_id', {
            containerId: 'd3c66d44-bd8f-4600-8b28-3c5e7cdb6b0a',
            incidentTime: '2026-01-23T20:14:55.9797441Z'
        });
        console.log('Result:', JSON.stringify(result2, null, 2));

        console.log('\n\n=== TEST 4: Call resolve_to_node_id WITH vmId ===');
        const result3 = await client.callTool('resolve_to_node_id', {
            vmId: '14b9cc89-0c2d-4884-a7b7-ff83270592cd',
            incidentTime: '2026-01-23T20:14:55.9797441Z'
        });
        console.log('Result:', JSON.stringify(result3, null, 2));

    } catch (error) {
        console.error('Error:', error);
    } finally {
        client.close();
        process.exit(0);
    }
}

main();
