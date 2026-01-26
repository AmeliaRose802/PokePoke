const { spawn } = require('child_process');
const readline = require('readline');

const SERVER_PATH = 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1';

async function listTools() {
    console.log('=' .repeat(80));
    console.log('LISTING ALL MCP TOOLS');
    console.log('='.repeat(80));
    console.log();
    console.log('Starting MCP server... (this takes ~12 seconds to build)');
    
    const server = spawn('pwsh', [
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', SERVER_PATH
    ], {
        stdio: ['pipe', 'pipe', 'pipe']
    });

    const rl = readline.createInterface({
        input: server.stdout,
        crlfDelay: Infinity
    });

    let messageId = 0;
    const pendingRequests = new Map();

    rl.on('line', (line) => {
        // Skip build output
        if (line.includes('Build succeeded') || line.includes('Time Elapsed') ||
            line.includes('Building') || line.includes('Copying') ||
            line.includes('Workload') || !line.trim()) {
            return;
        }

        try {
            const msg = JSON.parse(line);
            if (msg.id && pendingRequests.has(msg.id)) {
                const { resolve, reject } = pendingRequests.get(msg.id);
                pendingRequests.delete(msg.id);

                if (msg.error) {
                    reject(new Error(JSON.stringify(msg.error)));
                } else {
                    resolve(msg.result);
                }
            }
        } catch (e) {
            // Not JSON - skip
        }
    });

    function sendRequest(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++messageId;
            const message = { jsonrpc: '2.0', id, method, params };

            pendingRequests.set(id, { resolve, reject });
            server.stdin.write(JSON.stringify(message) + '\n');

            setTimeout(() => {
                if (pendingRequests.has(id)) {
                    pendingRequests.delete(id);
                    reject(new Error(`Timeout waiting for ${method}`));
                }
            }, 30000);
        });
    }

    // Wait for server to build
    await new Promise(resolve => setTimeout(resolve, 12000));

    try {
        // Initialize
        console.log('Initializing connection...');
        const initResult = await sendRequest('initialize', {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'tool-lister', version: '1.0.0' }
        });
        
        console.log(`✓ Connected to: ${initResult.serverInfo.name} v${initResult.serverInfo.version}`);
        console.log();

        // List tools
        console.log('Fetching tools...');
        const toolsResult = await sendRequest('tools/list', {});
        const tools = toolsResult.tools || [];

        console.log('='.repeat(80));
        console.log(`FOUND ${tools.length} TOOLS`);
        console.log('='.repeat(80));
        console.log();

        tools.forEach((tool, index) => {
            console.log(`${index + 1}. ${tool.name}`);
            console.log(`   Description: ${tool.description || 'No description'}`);
            
            if (tool.inputSchema && tool.inputSchema.properties) {
                console.log(`   Parameters:`);
                const props = tool.inputSchema.properties;
                const required = tool.inputSchema.required || [];
                
                Object.keys(props).forEach(param => {
                    const paramInfo = props[param];
                    const req = required.includes(param) ? ' (required)' : ' (optional)';
                    const type = paramInfo.type ? ` [${paramInfo.type}]` : '';
                    const desc = paramInfo.description || '';
                    console.log(`     - ${param}${req}${type}: ${desc}`);
                });
            }
            console.log();
        });

        console.log('='.repeat(80));
        console.log('TOOL SUMMARY BY CATEGORY');
        console.log('='.repeat(80));
        
        // Group by common prefixes
        const groups = {};
        tools.forEach(tool => {
            const name = tool.name;
            let category = 'Other';
            
            if (name.includes('resolve')) category = 'ID Resolution';
            else if (name.includes('kusto') || name.includes('query')) category = 'Kusto Queries';
            else if (name.includes('incident') || name.includes('folder')) category = 'Incident Management';
            else if (name.includes('workflow')) category = 'Workflows';
            else if (name.includes('health') || name.includes('check')) category = 'Health Checks';
            
            if (!groups[category]) groups[category] = [];
            groups[category].push(tool.name);
        });
        
        Object.keys(groups).sort().forEach(category => {
            console.log(`\n${category} (${groups[category].length}):`);
            groups[category].forEach(name => console.log(`  • ${name}`));
        });
        
        console.log('\n' + '='.repeat(80));
        console.log('✓ Complete!');
        
    } catch (error) {
        console.error('\n❌ ERROR:', error.message);
    } finally {
        server.kill();
        process.exit(0);
    }
}

listTools().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
