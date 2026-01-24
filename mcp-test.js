const { spawn } = require('child_process');

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

mcp.stdin.write(JSON.stringify(initRequest) + '\n');

mcp.stdout.on('data', (data) => {
  console.log('STDOUT:', data.toString());
});

mcp.stderr.on('data', (data) => {
  console.error('STDERR:', data.toString());
});

setTimeout(() => {
  // Send tools/list request
  const listRequest = {
    jsonrpc: "2.0",
    id: 2,
    method: "tools/list",
    params: {}
  };
  mcp.stdin.write(JSON.stringify(listRequest) + '\n');
}, 2000);

setTimeout(() => {
  mcp.kill();
  process.exit(0);
}, 5000);
