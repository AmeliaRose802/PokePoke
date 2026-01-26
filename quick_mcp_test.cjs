const { spawn } = require('child_process');

console.log('Quick MCP server test...');
const server = spawn('pwsh', [
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', 'c:\\Users\\ameliapayne\\icm_queue_c#\\start-mcp-server.ps1'
], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let gotOutput = false;
server.stdout.on('data', (data) => {
    gotOutput = true;
    const str = data.toString();
    if (str.trim() && !str.includes('Build') && !str.includes('Copying')) {
        console.log('OUTPUT:', str);
    }
});

setTimeout(() => {
    console.log(`Got output after 20s: ${gotOutput}`);
    if (gotOutput) {
        const msg = JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method: 'initialize',
            params: {
                protocolVersion: '2024-11-05',
                capabilities: {},
                clientInfo: { name: 'quick-test', version: '1.0' }
            }
        });
        console.log('Sending initialize...');
        server.stdin.write(msg + '\n');
        setTimeout(() => {
            console.log('No response in 10s');
            server.kill();
            process.exit(1);
        }, 10000);
    } else {
        console.log('Server never sent any output');
        server.kill();
        process.exit(1);
    }
}, 20000);
