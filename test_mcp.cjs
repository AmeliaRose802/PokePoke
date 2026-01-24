const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

// Use cmd.exe to run npx
const server = spawn('cmd.exe', ['/c', 'npx', 'enhanced-ado-mcp-server', 'msazure', '--area-path', 'ICM\\Azure Data', '--authentication', 'env'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: false
});

const rl = readline.createInterface({
    input: server.stdout,
    crlfDelay: Infinity
});

rl.on('line', (line) => {
    if (line.trim() && !line.includes('pm exec')) {
        try {
            const msg = JSON.parse(line);
            console.log('SERVER MSG:', JSON.stringify(msg, null, 2));
        } catch (e) {
            // Not JSON, might be log line
            if (line.includes('[INFO]') || line.includes('[ERROR]')) {
                console.log('LOG:', line);
            } else {
                console.log('OUTPUT:', line);
            }
        }
    }
});

server.stderr.on('data', (data) => {
    const str = data.toString();
    if (!str.includes('pm exec')) {
        console.error('STDERR:', str);
    }
});

server.on('error', (err) => {
    console.error('Process error:', err);
});

// Initialize the MCP protocol
const initMessage = {
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: {
            name: 'test-client',
            version: '1.0.0'
        }
    }
};

setTimeout(() => {
    console.log('\n=== Sending initialize ===');
    server.stdin.write(JSON.stringify(initMessage) + '\n');
}, 3000);

// List tools after initialization
setTimeout(() => {
    const listToolsMsg = {
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/list',
        params: {}
    };
    console.log('\n=== Sending tools/list ===');
    server.stdin.write(JSON.stringify(listToolsMsg) + '\n');
}, 5000);

setTimeout(() => {
    console.log('\n=== Cleaning up ===');
    server.kill();
    process.exit(0);
}, 10000);
