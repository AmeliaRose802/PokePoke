const { spawn } = require('child_process');
const readline = require('readline');

class MCPClient {
    constructor() {
        this.messageId = 0;
        this.pendingRequests = new Map();
        this.serverPath = 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1';
    }

    async start() {
        return new Promise((resolve, reject) => {
            console.log('Starting MCP server...');
            
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
                if (line.includes('Build succeeded') || line.includes('Time Elapsed') || 
                    line.includes('Building') || line.includes('Copying') || 
                    line.includes('Workload updates') || !line.trim()) {
                    return;
                }
                try {
                    const msg = JSON.parse(line);
                    this.handleMessage(msg);
                } catch (e) {}
            });

            this.server.on('error', (err) => reject(err));
            setTimeout(resolve, 15000);
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
            const message = { jsonrpc: '2.0', id, method, params };
            this.pendingRequests.set(id, { resolve, reject });
            this.server.stdin.write(JSON.stringify(message) + '\n');
            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error('Timeout for ' + method));
                }
            }, 60000);
        });
    }

    async initialize() {
        console.log('Initializing...');
        await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'task-catalog-test', version: '1.0.0' }
        });
        console.log('Initialized OK\n');
    }

    async callTool(name, args) {
        return await this.sendRequest('tools/call', { name, arguments: args });
    }

    close() {
        if (this.server) this.server.kill();
    }
}

async function testGetTaskCatalog() {
    const client = new MCPClient();
    try {
        await client.start();
        await client.initialize();
        
        console.log('='.repeat(80));
        console.log('TEST 1: get_task_catalog with format="summary"');
        console.log('='.repeat(80));
        console.log('Parameters: { format: "summary" }\n');
        
        const result1 = await client.callTool('get_task_catalog', { format: 'summary' });
        console.log('OUTPUT:');
        console.log(JSON.stringify(result1, null, 2));
        console.log('\n');
        
        console.log('='.repeat(80));
        console.log('TEST 2: get_task_catalog with format="detailed", includeSchema=true');
        console.log('='.repeat(80));
        console.log('Parameters: { format: "detailed", includeSchema: true }\n');
        
        const result2 = await client.callTool('get_task_catalog', { 
            format: 'detailed', 
            includeSchema: true 
        });
        console.log('OUTPUT:');
        console.log(JSON.stringify(result2, null, 2));
        console.log('\n');
        
        console.log('='.repeat(80));
        console.log('TEST 3: get_task_catalog with format="detailed", includeSchema=false');
        console.log('='.repeat(80));
        console.log('Parameters: { format: "detailed", includeSchema: false }\n');
        
        const result3 = await client.callTool('get_task_catalog', { 
            format: 'detailed', 
            includeSchema: false 
        });
        console.log('OUTPUT:');
        console.log(JSON.stringify(result3, null, 2));
        console.log('\n');
        
        console.log('='.repeat(80));
        console.log('ANALYSIS');
        console.log('='.repeat(80));
        
        // Extract content from responses
        const getContent = (result) => {
            if (result.content && Array.isArray(result.content)) {
                return result.content.map(c => c.text || '').join('\n');
            }
            return '';
        };
        
        const content1 = getContent(result1);
        const content2 = getContent(result2);
        const content3 = getContent(result3);
        
        console.log('\nTest 1 (summary) length:', content1.length);
        console.log('Test 2 (detailed, includeSchema=true) length:', content2.length);
        console.log('Test 3 (detailed, includeSchema=false) length:', content3.length);
        
        console.log('\nComparing Test 2 vs Test 3:');
        if (content2 === content3) {
            console.log('❌ IDENTICAL - includeSchema parameter has NO EFFECT');
        } else {
            console.log('✓ DIFFERENT - includeSchema parameter WORKS');
            console.log('  Difference in length:', Math.abs(content2.length - content3.length));
        }
        
        // Check for schema-related content
        const hasSchemaKeywords = (text) => {
            const keywords = ['schema', 'type:', 'properties', 'required', 'inputSchema'];
            return keywords.some(kw => text.toLowerCase().includes(kw.toLowerCase()));
        };
        
        console.log('\nSchema keywords in Test 2 (includeSchema=true):', hasSchemaKeywords(content2));
        console.log('Schema keywords in Test 3 (includeSchema=false):', hasSchemaKeywords(content3));
        
        console.log('\n='.repeat(80));
        console.log('VERDICT ON BUG PokePoke-9lc');
        console.log('='.repeat(80));
        
        if (content2 === content3) {
            console.log('✓ BUG CONFIRMED: includeSchema parameter does nothing');
        } else {
            console.log('✗ BUG NOT REPRODUCED: includeSchema parameter appears to work');
        }
        
    } catch (error) {
        console.error('ERROR:', error.message);
        process.exit(1);
    } finally {
        client.close();
        setTimeout(() => process.exit(0), 1000);
    }
}

testGetTaskCatalog();
