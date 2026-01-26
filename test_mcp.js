const { spawn } = require('child_process');

// Start the MCP server
const server = spawn('npx', ['enhanced-ado-mcp-server', 'msazure', '--area-path', 'ICM\\Azure Data', '--authentication', 'env'], {
    stdio: ['pipe', 'pipe', 'pipe']
});

let buffer = '';

server.stdout.on('data', (data) => {
    buffer += data.toString();
    // Try to parse JSON-RPC messages
    const lines = buffer.split('\n');
    buffer = lines.pop(); // Keep incomplete line in buffer
    
    lines.forEach(line => {
        if (line.trim()) {
            console.log('SERVER:', line);
        }
    });
});

server.stderr.on('data', (data) => {
    console.error('STDERR:', data.toString());
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
    console.log('Sending initialize...');
    server.stdin.write(JSON.stringify(initMessage) + '\n');
}, 1000);

setTimeout(() => {
    console.log('Done waiting');
    server.kill();
    process.exit(0);
}, 5000);
