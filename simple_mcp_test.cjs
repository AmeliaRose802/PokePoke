const { spawn } = require('child_process');

const server = spawn('pwsh', [
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1'
], {
    stdio: ['pipe', 'pipe', 'pipe']
});

let outputCount = 0;
server.stdout.on('data', (data) => {
    outputCount++;
    console.log(`STDOUT[${outputCount}]:`, data.toString());
});

server.stderr.on('data', (data) => {
    console.log('STDERR:', data.toString());
});

server.on('error', (err) => {
    console.error('ERROR:', err);
});

setTimeout(() => {
    console.log('\n\n=== Sending initialize request ===');
    const initMsg = {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'test', version: '1.0' }
        }
    };
    console.log('Sending:', JSON.stringify(initMsg));
    server.stdin.write(JSON.stringify(initMsg) + '\n');
}, 10000);

setTimeout(() => {
    console.log('\n\n=== Timeout - Killing server ===');
    server.kill();
    process.exit(1);
}, 20000);
