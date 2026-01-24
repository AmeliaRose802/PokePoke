import { spawn } from 'child_process';

const mcp = spawn('npx', ['@azure/mcp'], {
  stdio: ['pipe', 'pipe', 'pipe']
});

// Send initialize request
const initRequest = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "test", version: "1.0" }
  }
};

let buffer = '';

mcp.stdout.on('data', (data) => {
  buffer += data.toString();
  const lines = buffer.split('\n');
  buffer = lines.pop();
  
  lines.forEach(line => {
    if (line.trim()) {
      console.log('RESPONSE:', line);
      try {
        const response = JSON.parse(line);
        if (response.id === 1) {
          // After init, send tools/list
          const listRequest = {
            jsonrpc: "2.0",
            id: 2,
            method: "tools/list",
            params: {}
          };
          mcp.stdin.write(JSON.stringify(listRequest) + '\n');
        } else if (response.id === 2) {
          console.log('TOOLS:', JSON.stringify(response.result, null, 2));
          mcp.kill();
          process.exit(0);
        }
      } catch (e) {
        console.error('Parse error:', e.message);
      }
    }
  });
});

mcp.stderr.on('data', (data) => {
  console.error('STDERR:', data.toString());
});

mcp.stdin.write(JSON.stringify(initRequest) + '\n');

setTimeout(() => {
  console.log('Timeout reached');
  mcp.kill();
  process.exit(1);
}, 10000);
