const { spawn } = require('child_process');
const readline = require('readline');

class MCPClient {
    constructor() {
        this.messageId = 0;
        this.pendingRequests = new Map();
        this.initialized = false;
        this.serverPath = 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1';
    }

    async start() {
        return new Promise((resolve, reject) => {
            console.log(`Starting MCP server from: ${this.serverPath}`);
            console.log('Please wait while the server builds and starts...\n');
            
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

            this.rl.on('line', (line) => {
                // Skip build output
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
                }
            });

            this.server.stderr.on('data', (data) => {
                // Suppress most stderr
            });

            this.server.on('error', (err) => {
                console.error('Server process error:', err);
                reject(err);
            });

            // Wait for server to build and start (needs time to compile)
            setTimeout(resolve, 12000);
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

            // Longer timeout for Kusto queries
            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error(`Request timeout for ${method}`));
                }
            }, 60000);
        });
    }

    async initialize() {
        console.log('Initializing MCP connection...');
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: {
                name: 'tool-lister-client',
                version: '1.0.0'
            }
        });
        this.initialized = true;
        console.log('✓ Initialized successfully');
        console.log(`  Server: ${result.serverInfo.name} v${result.serverInfo.version}\n`);
        return result;
    }

    async listTools() {
        const result = await this.sendRequest('tools/list', {});
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
        
        console.log('=' .repeat(80));
        console.log('LISTING ALL AVAILABLE MCP TOOLS');
        console.log('='.repeat(80));
        console.log();
        
        const toolsResult = await client.listTools();
        const tools = toolsResult.tools || [];
        
        console.log(`Found ${tools.length} tools:\n`);
        
        // Check for specific tools the user is interested in
        const interestedTools = ['resolve_to_node_id', 'create_incident_folder'];
        const foundInterested = [];
        
        tools.forEach((tool, index) => {
            const num = String(index + 1).padStart(2, ' ');
            console.log(`${num}. ${tool.name}`);
            console.log(`    Description: ${tool.description || 'No description'}`);
            
            // Show input schema if available
            if (tool.inputSchema) {
                const props = tool.inputSchema.properties;
                if (props && Object.keys(props).length > 0) {
                    console.log(`    Parameters:`);
                    Object.keys(props).forEach(param => {
                        const paramInfo = props[param];
                        const required = (tool.inputSchema.required || []).includes(param);
                        const requiredMark = required ? ' (required)' : ' (optional)';
                        console.log(`      - ${param}${requiredMark}: ${paramInfo.description || paramInfo.type || ''}`);
                    });
                }
            }
            console.log();
            
            // Check if this is a tool the user is interested in
            if (interestedTools.includes(tool.name)) {
                foundInterested.push(tool.name);
            }
        });
        
        console.log('='.repeat(80));
        console.log('SUMMARY');
        console.log('='.repeat(80));
        console.log(`Total tools: ${tools.length}`);
        console.log();
        
        console.log('Tools related to your search:');
        interestedTools.forEach(name => {
            const found = foundInterested.includes(name);
            const mark = found ? '✓' : '✗';
            console.log(`  ${mark} ${name}: ${found ? 'FOUND' : 'NOT FOUND'}`);
        });
        
        console.log();
        console.log('Tools related to incident investigation:');
        const investigationTools = tools.filter(t => 
            t.name.toLowerCase().includes('incident') ||
            t.name.toLowerCase().includes('investigate') ||
            t.name.toLowerCase().includes('kusto') ||
            t.name.toLowerCase().includes('query') ||
            t.name.toLowerCase().includes('resolve') ||
            t.name.toLowerCase().includes('node') ||
            t.name.toLowerCase().includes('health') ||
            t.name.toLowerCase().includes('check')
        );
        
        if (investigationTools.length > 0) {
            investigationTools.forEach(tool => {
                console.log(`  • ${tool.name}`);
            });
        } else {
            console.log('  (None found matching common investigation keywords)');
        }
        
        console.log();
        console.log('='.repeat(80));
        
    } catch (error) {
        console.error('\n❌ ERROR:', error.message);
        if (error.stack) {
            console.error(error.stack);
        }
        process.exit(1);
    } finally {
        console.log('\nClosing connection...');
        client.close();
        setTimeout(() => process.exit(0), 1000);
    }
}

main();
