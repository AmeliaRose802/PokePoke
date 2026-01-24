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
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', this.serverPath
            ], { stdio: ['pipe', 'pipe', 'pipe'] });

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

            console.log('Waiting 10 seconds for server startup...');
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
        console.log('Initializing...');
        await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'query-schema-test', version: '1.0.0' }
        });
        console.log('OK - Initialized\n');
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
        
        console.log('='.repeat(80));
        console.log('STEP 1: List tools');
        console.log('='.repeat(80));
        const toolsResult = await client.listTools();
        
        const listQueriesToolDef = toolsResult.tools.find(t => t.name === 'list_kusto_queries');
        const getSchemaToolDef = toolsResult.tools.find(t => t.name === 'get_query_schema');
        
        console.log('list_kusto_queries: ' + (listQueriesToolDef ? 'FOUND' : 'MISSING'));
        console.log('get_query_schema: ' + (getSchemaToolDef ? 'FOUND' : 'MISSING'));

        if (!listQueriesToolDef || !getSchemaToolDef) {
            console.log('ERROR: Required tools missing!');
            exitCode = 1;
            return;
        }

        console.log('\n='.repeat(80));
        console.log('STEP 2: Call list_kusto_queries');
        console.log('='.repeat(80));
        const listResult = await client.callTool('list_kusto_queries', {});
        
        let queriesList = [];
        if (listResult.content && Array.isArray(listResult.content)) {
            for (const item of listResult.content) {
                if (item.type === 'text') {
                    // Parse the JSON response
                    try {
                        const data = JSON.parse(item.text);
                        if (data.success && data.data && data.data.queries) {
                            queriesList = data.data.queries.map(q => q.name);
                            console.log('Parsed ' + queriesList.length + ' queries from JSON response');
                            console.log('Sample queries:', queriesList.slice(0, 5).join(', '));
                        }
                    } catch (e) {
                        console.log('Failed to parse JSON:', e.message);
                    }
                }
            }
        }

        if (queriesList.length === 0) {
            console.log('ERROR: No queries found!');
            exitCode = 1;
            return;
        }

        // Test multiple queries to get better coverage
        const testQueries = [queriesList[0], queriesList[Math.floor(queriesList.length / 2)]];
        console.log('\nTesting queries:', testQueries.join(', '));

        for (const testQueryName of testQueries) {
            console.log('\n' + '='.repeat(80));
            console.log('STEP 3: Call get_query_schema for "' + testQueryName + '"');
            console.log('='.repeat(80));
            
            const schemaResult = await client.callTool('get_query_schema', {
                queryName: testQueryName
            });
            
            let schemaText = '';
            if (schemaResult.content && Array.isArray(schemaResult.content)) {
                for (const item of schemaResult.content) {
                    if (item.type === 'text') {
                        schemaText = item.text;
                        console.log('\nSchema content:\n' + schemaText);
                    }
                }
            }

            if (schemaResult.isError) {
                console.log('ERROR: Tool returned error');
                continue;
            }

            console.log('\n' + '-'.repeat(80));
            console.log('ANALYSIS for ' + testQueryName);
            console.log('-'.repeat(80));

            const checks = {
                hasParameters: /parameter|input|argument/i.test(schemaText),
                hasTypes: /string|int|datetime|bool|type/i.test(schemaText),
                hasDescription: /description|purpose|returns|output/i.test(schemaText),
                hasExample: /example|sample/i.test(schemaText),
                hasRequiredInfo: /required|optional|mandatory/i.test(schemaText),
                hasClusterInfo: /cluster|database/i.test(schemaText),
                notEmpty: schemaText.length > 10,
                notJustName: schemaText.length > testQueryName.length + 20,
                notError: !schemaText.includes('error') && !schemaText.includes('failed')
            };

            console.log('Schema Quality Checks:');
            console.log('  Not empty: ' + checks.notEmpty);
            console.log('  More than just name: ' + checks.notJustName);
            console.log('  Not an error: ' + checks.notError);
            console.log('  Has parameters: ' + checks.hasParameters);
            console.log('  Has types: ' + checks.hasTypes);
            console.log('  Has descriptions: ' + checks.hasDescription);
            console.log('  Has examples: ' + checks.hasExample);
            console.log('  Has required/optional: ' + checks.hasRequiredInfo);
            console.log('  Has cluster/database: ' + checks.hasClusterInfo);

            const passCount = Object.values(checks).filter(v => v).length;
            const totalChecks = Object.keys(checks).length;
            const score = (passCount / totalChecks * 100).toFixed(0);
            console.log('\nScore: ' + passCount + '/' + totalChecks + ' (' + score + '%)');
        }

        console.log('\n' + '='.repeat(80));
        console.log('OVERALL VERDICT');
        console.log('='.repeat(80));
        console.log('\nBased on testing ' + testQueries.length + ' queries:\n');
        console.log('USEFULNESS FOR INCIDENT INVESTIGATION:');
        console.log('');
        console.log('1. DISCOVERABILITY: Can I find what queries exist?');
        console.log('   list_kusto_queries works and returns ' + queriesList.length + ' queries');
        console.log('   ✓ GOOD - Can discover available queries');
        console.log('');
        console.log('2. SCHEMA INFORMATION: Can I understand how to use a query?');
        console.log('   Need to analyze the schema responses...');
        console.log('');
        console.log('Key question: Does get_query_schema provide enough info to');
        console.log('construct a valid query call without guessing?');
        console.log('');
        console.log('An AI would need:');
        console.log('  • Parameter names (what inputs are needed)');
        console.log('  • Parameter types (string, datetime, int, etc.)');
        console.log('  • Required vs optional parameters');
        console.log('  • Parameter descriptions (what each one means)');
        console.log('  • Example values (format expectations)');
        console.log('  • What the query returns (output schema)');

    } catch (error) {
        console.error('\nERROR: ' + error.message);
        console.error(error.stack);
        exitCode = 1;
    } finally {
        console.log('\nCleaning up...');
        client.close();
        setTimeout(() => process.exit(exitCode), 1000);
    }
}

runTests();
