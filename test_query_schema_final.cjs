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

            console.log('Waiting for server to build and start (15 seconds)...');
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
            }, 60000);
        });
    }

    async initialize() {
        console.log('\n=== Initializing MCP connection ===');
        const result = await this.sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: {
                name: 'query-schema-test-client',
                version: '1.0.0'
            }
        });
        console.log('✓ Initialized successfully');
        console.log(`Server: ${result.serverInfo.name} v${result.serverInfo.version}`);
        return result;
    }

    async listTools() {
        return await this.sendRequest('tools/list', {});
    }

    async callTool(name, args) {
        console.log(`\n=== Calling tool: ${name} ===`);
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
    const client = new MCPClient();
    let exitCode = 0;
    
    try {
        await client.start();
        await client.initialize();
        
        // List tools
        const toolsResult = await client.listTools();
        console.log(`\n✓ Found ${toolsResult.tools.length} tools`);
        
        const listQueriesToolDef = toolsResult.tools.find(t => t.name === 'list_kusto_queries');
        const getSchemaToolDef = toolsResult.tools.find(t => t.name === 'get_query_schema');
        
        console.log(`\nChecking for required tools:`);
        console.log(`  list_kusto_queries: ${listQueriesToolDef ? '✓ FOUND' : '✗ MISSING'}`);
        console.log(`  get_query_schema: ${getSchemaToolDef ? '✓ FOUND' : '✗ MISSING'}`);

        if (!listQueriesToolDef || !getSchemaToolDef) {
            console.log('\n❌ CRITICAL: Required tools are missing!');
            exitCode = 1;
            return;
        }

        console.log('\n' + '='.repeat(80));
        console.log('TEST 1: Call list_kusto_queries to get available queries');
        console.log('='.repeat(80));
        
        const listResult = await client.callTool('list_kusto_queries', {});
        console.log('Response received');
        
        let queriesList = [];
        if (listResult.content && Array.isArray(listResult.content)) {
            for (const item of listResult.content) {
                if (item.type === 'text') {
                    try {
                        const data = JSON.parse(item.text);
                        if (data.success && data.data && data.data.queries) {
                            queriesList = data.data.queries;
                            console.log(`✓ Parsed ${queriesList.length} queries from response`);
                            console.log(`\nFirst 5 queries:`);
                            queriesList.slice(0, 5).forEach((q, i) => {
                                console.log(`  ${i+1}. ${q.name} - ${q.description.substring(0, 60)}...`);
                            });
                        }
                    } catch (e) {
                        console.log('Failed to parse JSON:', e.message);
                    }
                }
            }
        }

        if (queriesList.length === 0) {
            console.log('❌ ERROR: No queries found!');
            exitCode = 1;
            return;
        }

        // Test get_query_schema on a few queries
        const testQueries = [queriesList[0], queriesList[5] || queriesList[1]];
        
        for (let i = 0; i < testQueries.length; i++) {
            const query = testQueries[i];
            console.log('\n' + '='.repeat(80));
            console.log(`TEST ${i+2}: Call get_query_schema for "${query.name}"`);
            console.log('='.repeat(80));
            console.log(`Description: ${query.description}`);
            console.log(`Expected parameters from list: ${query.parameters.map(p => `${p.name}:${p.type}`).join(', ')}`);
            
            const schemaResult = await client.callTool('get_query_schema', {
                queryName: query.name
            });
            
            let schemaText = '';
            if (schemaResult.content && Array.isArray(schemaResult.content)) {
                for (const item of schemaResult.content) {
                    if (item.type === 'text') {
                        schemaText = item.text;
                    }
                }
            }

            if (schemaResult.isError || schemaText.includes('error')) {
                console.log('❌ ERROR: Tool returned error');
                console.log(schemaText);
                continue;
            }

            console.log('\n📄 Schema Response:');
            console.log(schemaText);

            // Analysis
            console.log('\n📊 Schema Quality Analysis:');
            
            const checks = {
                notEmpty: schemaText.length > 20,
                hasParameters: /parameter|input|argument/i.test(schemaText),
                hasTypes: /string|int|datetime|bool|type/i.test(schemaText),
                hasDescription: /description|purpose|returns|output/i.test(schemaText),
                hasExample: /example|sample/i.test(schemaText),
                hasRequiredInfo: /required|optional|mandatory/i.test(schemaText),
                hasClusterInfo: /cluster|database/i.test(schemaText),
                hasQueryBody: /let |\\n|kusto/i.test(schemaText)
            };

            Object.entries(checks).forEach(([key, value]) => {
                const label = key.replace(/([A-Z])/g, ' $1').toLowerCase();
                console.log(`  ${value ? '✓' : '✗'} ${label}`);
            });

            const passCount = Object.values(checks).filter(v => v).length;
            const totalChecks = Object.keys(checks).length;
            const score = (passCount / totalChecks * 100).toFixed(0);
            console.log(`\n  Score: ${passCount}/${totalChecks} (${score}%)`);
        }

        // Final verdict
        console.log('\n' + '='.repeat(80));
        console.log('FINAL VERDICT: Is get_query_schema useful for incident investigation?');
        console.log('='.repeat(80));
        console.log('\n📋 Summary:\n');
        console.log('✓ list_kusto_queries successfully returns ' + queriesList.length + ' queries');
        console.log('✓ Each query includes: name, description, category, parameters with types');
        console.log('\n❓ get_query_schema adds value IF it provides:');
        console.log('  1. Usage examples with actual values');
        console.log('  2. Output schema (what columns/fields are returned)');
        console.log('  3. Additional context not in list_kusto_queries');
        console.log('  4. The actual Kusto query body/template');
        console.log('\n🤔 Assessment:');
        console.log('Check the schema responses above to determine if get_query_schema');
        console.log('provides enough ADDITIONAL information beyond what list_kusto_queries');
        console.log('already gives us.');

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
