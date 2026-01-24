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
                } catch (e) {
                    // Not JSON
                }
            });

            this.server.stderr.on('data', (data) => {
                const str = data.toString();
                if (str.includes('[ERROR]')) {
                    console.error('STDERR:', str);
                }
            });

            this.server.on('error', (err) => {
                console.error('Server process error:', err);
                reject(err);
            });

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

            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error(`Request timeout for ${method}`));
                }
            }, 30000);
        });
    }

    async initialize() {
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: {
                name: 'kusto-queries-test',
                version: '1.0.0'
            }
        });
        this.initialized = true;
        return result;
    }

    async listTools() {
        return await this.sendRequest('tools/list', {});
    }

    async callTool(name, args) {
        return await this.sendRequest('tools/call', {
            name,
            arguments: args
        });
    }

    close() {
        if (this.server) {
            this.server.kill();
        }
    }
}

const testResults = [];

function logTest(testName, params, success, data, error = null) {
    const result = { testName, params, success, data, error, timestamp: new Date().toISOString() };
    testResults.push(result);
    return result;
}

async function runTests() {
    const client = new MCPClient();
    
    try {
        console.log('='.repeat(80));
        console.log('COMPREHENSIVE TEST: list_kusto_queries MCP Tool');
        console.log('='.repeat(80));
        console.log();
        
        await client.start();
        const initResult = await client.initialize();
        console.log(`✓ Connected to: ${initResult.serverInfo.name} v${initResult.serverInfo.version}\n`);
        
        const toolsResult = await client.listTools();
        const listKustoTool = toolsResult.tools.find(t => t.name === 'list_kusto_queries');
        
        if (!listKustoTool) {
            console.log('❌ CRITICAL: list_kusto_queries tool NOT FOUND!\n');
            console.log('Available tools:');
            toolsResult.tools.forEach(t => console.log(`  - ${t.name}`));
            return;
        }
        
        console.log('✓ Found list_kusto_queries tool');
        console.log(`  Description: ${listKustoTool.description}`);
        console.log(`  Input Schema:`);
        console.log(JSON.stringify(listKustoTool.inputSchema, null, 4));
        console.log();
        
        // TEST 1: No parameters
        console.log('='.repeat(80));
        console.log('TEST 1: No parameters');
        console.log('='.repeat(80));
        try {
            const result = await client.callTool('list_kusto_queries', {});
            console.log('✓ SUCCESS');
            console.log('Response:', JSON.stringify(result, null, 2));
            logTest('No parameters', {}, true, result);
        } catch (error) {
            console.log('❌ FAILED:', error.message);
            logTest('No parameters', {}, false, null, error.message);
        }
        console.log();
        
        // TEST 2: Categories
        const categories = ['performance', 'error', 'security', 'diagnostics', 'troubleshooting'];
        for (const category of categories) {
            console.log('='.repeat(80));
            console.log(`TEST 2.${categories.indexOf(category) + 1}: Category "${category}"`);
            console.log('='.repeat(80));
            try {
                const result = await client.callTool('list_kusto_queries', { category });
                console.log('✓ SUCCESS');
                console.log('Response:', JSON.stringify(result, null, 2));
                logTest(`Category: ${category}`, { category }, true, result);
            } catch (error) {
                console.log('❌ FAILED:', error.message);
                logTest(`Category: ${category}`, { category }, false, null, error.message);
            }
            console.log();
        }
        
        // TEST 3: Search terms
        const searchTerms = ['error', 'performance', 'security', 'latency', 'failure'];
        for (const search of searchTerms) {
            console.log('='.repeat(80));
            console.log(`TEST 3.${searchTerms.indexOf(search) + 1}: Search "${search}"`);
            console.log('='.repeat(80));
            try {
                const result = await client.callTool('list_kusto_queries', { search });
                console.log('✓ SUCCESS');
                console.log('Response:', JSON.stringify(result, null, 2));
                logTest(`Search: ${search}`, { search }, true, result);
            } catch (error) {
                console.log('❌ FAILED:', error.message);
                logTest(`Search: ${search}`, { search }, false, null, error.message);
            }
            console.log();
        }
        
        // TEST 4: Combined
        const combinedTests = [
            { category: 'performance', search: 'latency' },
            { category: 'error', search: 'failure' }
        ];
        for (const params of combinedTests) {
            console.log('='.repeat(80));
            console.log(`TEST 4.${combinedTests.indexOf(params) + 1}: Combined ${JSON.stringify(params)}`);
            console.log('='.repeat(80));
            try {
                const result = await client.callTool('list_kusto_queries', params);
                console.log('✓ SUCCESS');
                console.log('Response:', JSON.stringify(result, null, 2));
                logTest(`Combined: ${JSON.stringify(params)}`, params, true, result);
            } catch (error) {
                console.log('❌ FAILED:', error.message);
                logTest(`Combined: ${JSON.stringify(params)}`, params, false, null, error.message);
            }
            console.log();
        }
        
        // SUMMARY
        console.log('='.repeat(80));
        console.log('TEST SUMMARY');
        console.log('='.repeat(80));
        const totalTests = testResults.length;
        const successfulTests = testResults.filter(r => r.success).length;
        const failedTests = totalTests - successfulTests;
        console.log(`Total: ${totalTests}, ✓ Success: ${successfulTests}, ❌ Failed: ${failedTests}`);
        
        console.log('\n' + '='.repeat(80));
        console.log('DETAILED RESULTS:');
        console.log('='.repeat(80));
        for (const result of testResults) {
            console.log(`\n${result.success ? '✓' : '❌'} ${result.testName}`);
            console.log(`  Parameters: ${JSON.stringify(result.params)}`);
            if (result.success && result.data && result.data.content) {
                const content = result.data.content.find(c => c.type === 'text');
                if (content) {
                    const preview = content.text.substring(0, 150).replace(/\n/g, ' ');
                    console.log(`  Response: ${preview}...`);
                }
            } else if (!result.success) {
                console.log(`  Error: ${result.error}`);
            }
        }
        
        console.log('\n' + '='.repeat(80));
        console.log('ASSESSMENT FOR INCIDENT INVESTIGATION');
        console.log('='.repeat(80));
        console.log('\n1. FUNCTIONALITY:');
        console.log(successfulTests === totalTests ? '   ✓ All tests passed' : `   ⚠ ${failedTests} tests failed`);
        
        console.log('\n2. USEFULNESS:');
        console.log('   - Provides curated Kusto queries for incident investigation');
        console.log('   - Filterable by category and searchable');
        console.log('   - Saves time during high-pressure incidents');
        
        console.log('\n3. SUGGESTED IMPROVEMENTS:');
        console.log('   - Add query parameter documentation');
        console.log('   - Include example usage and expected outputs');
        console.log('   - Add execution time estimates');
        console.log('   - Link to related diagnostic tools');
        
    } catch (error) {
        console.error('\n❌ Fatal error:', error.message);
        console.error(error.stack);
    } finally {
        client.close();
        setTimeout(() => process.exit(0), 1000);
    }
}

runTests();
