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
            console.log('Starting MCP server from: ' + this.serverPath);
            
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
                    if (line.includes('[INFO]') || line.includes('[ERROR]') || line.includes('[DEBUG]')) {
                        console.log('LOG:', line);
                    }
                }
            });

            this.server.stderr.on('data', (data) => {
                const str = data.toString();
                if (str.includes('[ERROR]')) {
                    console.error('STDERR:', str);
                }
            });

            this.server.on('error', (err) => {
                console.error('Server error:', err);
                reject(err);
            });

            console.log('Waiting for server (10 seconds)...');
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
        console.log('\n=== Initializing ===');
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'query-schema-test', version: '1.0.0' }
        });
        console.log('OK Initialized');
        return result;
    }

    async listTools() {
        return await this.sendRequest('tools/list', {});
    }

    async callTool(name, args) {
        return await this.sendRequest('tools/call', { name, arguments: args });
    }

    close() {
        if (this.server) {
            this.server.kill();
        }
    }
}

async function runTests() {
    const client = new MCPClient();
    let exitCode = 0;
    try {
        await client.start();
        await client.initialize();
        
        console.log('\n' + '='.repeat(80));
        console.log('STEP 1: List tools');
        console.log('='.repeat(80));
        const toolsResult = await client.listTools();
        console.log('Found ' + toolsResult.tools.length + ' tools');
        
        const listQueriesToolDef = toolsResult.tools.find(t => t.name === 'list_kusto_queries');
        const getSchemaToolDef = toolsResult.tools.find(t => t.name === 'get_query_schema');
        
        console.log('list_kusto_queries: ' + (listQueriesToolDef ? 'FOUND' : 'MISSING'));
        console.log('get_query_schema: ' + (getSchemaToolDef ? 'FOUND' : 'MISSING'));

        if (!listQueriesToolDef || !getSchemaToolDef) {
            console.log('ERROR: Required tools missing!');
            exitCode = 1;
            return;
        }

        console.log('\nlist_kusto_queries definition:');
        console.log('  Description: ' + listQueriesToolDef.description);
        console.log('  Input Schema: ' + JSON.stringify(listQueriesToolDef.inputSchema));
        
        console.log('\nget_query_schema definition:');
        console.log('  Description: ' + getSchemaToolDef.description);
        console.log('  Input Schema: ' + JSON.stringify(getSchemaToolDef.inputSchema));

        console.log('\n' + '='.repeat(80));
        console.log('STEP 2: Call list_kusto_queries');
        console.log('='.repeat(80));
        const listResult = await client.callTool('list_kusto_queries', {});
        console.log('Response: ' + JSON.stringify(listResult, null, 2));
        
        let queriesList = [];
        if (listResult.content && Array.isArray(listResult.content)) {
            for (const item of listResult.content) {
                if (item.type === 'text') {
                    console.log('\nText: ' + item.text);
                    const lines = item.text.split('\n');
                    queriesList = lines.filter(line => line.trim() && !line.includes('Available') && !line.includes('queries:'));
                }
            }
        }

        if (queriesList.length === 0) {
            console.log('ERROR: No queries found!');
            exitCode = 1;
            return;
        }
        console.log('Found ' + queriesList.length + ' queries');

        const testQueryName = queriesList[0].trim().replace(/^[-•*]\s*/, '');
        console.log('Using: ' + testQueryName);

        console.log('\n' + '='.repeat(80));
        console.log('STEP 3: Call get_query_schema for "' + testQueryName + '"');
        console.log('='.repeat(80));
        const schemaResult = await client.callTool('get_query_schema', { query_name: testQueryName });
        console.log('Response: ' + JSON.stringify(schemaResult, null, 2));
        
        let schemaText = '';
        if (schemaResult.content && Array.isArray(schemaResult.content)) {
            for (const item of schemaResult.content) {
                if (item.type === 'text') {
                    schemaText = item.text;
                    console.log('\nSchema:\n' + schemaText);
                }
            }
        }

        console.log('\n' + '='.repeat(80));
        console.log('STEP 4: Analyze usefulness');
        console.log('='.repeat(80));

        const checks = {
            hasParameters: /parameter|input|argument/i.test(schemaText),
            hasTypes: /string|int|datetime|bool|type/i.test(schemaText),
            hasDescription: /description|purpose|returns|output/i.test(schemaText),
            hasExample: /example|sample/i.test(schemaText),
            hasRequiredInfo: /required|optional|mandatory/i.test(schemaText),
            notEmpty: schemaText.length > 10,
            notJustName: schemaText.length > testQueryName.length + 20
        };

        console.log('Schema Quality:');
        console.log('  Not empty: ' + checks.notEmpty);
        console.log('  More than name: ' + checks.notJustName);
        console.log('  Has parameters: ' + checks.hasParameters);
        console.log('  Has types: ' + checks.hasTypes);
        console.log('  Has descriptions: ' + checks.hasDescription);
        console.log('  Has examples: ' + checks.hasExample);
        console.log('  Has required/optional: ' + checks.hasRequiredInfo);

        const passCount = Object.values(checks).filter(v => v).length;
        const totalChecks = Object.keys(checks).length;
        const score = (passCount / totalChecks * 100).toFixed(0);
        console.log('\nScore: ' + passCount + '/' + totalChecks + ' (' + score + '%)');

        console.log('\n' + '='.repeat(80));
        console.log('VERDICT');
        console.log('='.repeat(80));
        if (score >= 70) {
            console.log('HIGHLY USEFUL - Good info for incident investigation');
        } else if (score >= 50) {
            console.log('MODERATELY USEFUL - Missing some details');
        } else {
            console.log('LIMITED USEFULNESS - Needs more info');
            exitCode = 1;
        }

    } catch (error) {
        console.error('ERROR: ' + error.message);
        console.error(error.stack);
        exitCode = 1;
    } finally {
        console.log('\nCleaning up...');
        client.close();
        setTimeout(() => process.exit(exitCode), 1000);
    }
}

runTests();
