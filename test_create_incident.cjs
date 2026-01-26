const { spawn } = require('child_process');
const readline = require('readline');

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

            // Timeout after 60 seconds
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
                name: 'create-incident-test',
                version: '1.0.0'
            }
        });
        this.initialized = true;
        console.log('✓ Initialized successfully');
        console.log(`Server: ${result.serverInfo.name} v${result.serverInfo.version}`);
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

async function testCreateIncidentFolder() {
    const client = new ICMMCPClient();
    let exitCode = 0;
    
    try {
        await client.start();
        await client.initialize();
        
        console.log('\n' + '='.repeat(80));
        console.log('TEST: Create incident folder with incident_id=737661947');
        console.log('='.repeat(80));
        
        const result = await client.callTool('create_incident_folder', {
            incident_id: '737661947'
        });
        
        console.log('\n✓ Tool call completed successfully');
        console.log('\nFull Result:');
        console.log(JSON.stringify(result, null, 2));
        
        // Parse and display the result content
        if (result.content && result.content.length > 0) {
            console.log('\n=== Tool Response Details ===');
            result.content.forEach((item, index) => {
                if (item.type === 'text') {
                    console.log(`\nContent ${index + 1}:`);
                    console.log(item.text);
                }
            });
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

testCreateIncidentFolder();
