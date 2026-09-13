const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = 5180;
let agentProcess = null;
let config = {
  backendUrl: 'http://localhost:3000',
  agentId: '',
  agentSecret: 'change-me-agent-secret',
  stations: [],
};

// Load saved config
const configPath = path.join(__dirname, 'config.json');
if (fs.existsSync(configPath)) {
  try {
    config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch {}
}

function saveConfig() {
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
}

// Detect printers using Python agent
function detectPrinters() {
  return new Promise((resolve) => {
    const python = spawn('python', ['-m', 'nexino_agent', 'detect'], {
      cwd: path.join(__dirname, '..'),
      shell: true,
      env: { ...process.env, PYTHONPATH: path.join(__dirname, '..') },
    });

    let output = '';
    python.stdout.on('data', (d) => { output += d.toString(); });
    python.stderr.on('data', (d) => { output += d.toString(); });
    python.on('close', () => {
      try {
        resolve({ success: true, printers: JSON.parse(output) });
      } catch {
        resolve({ success: false, error: output, printers: [] });
      }
    });
  });
}

// Register stations
async function registerStations(agentId) {
  const printers = await detectPrinters();
  if (!printers.success || printers.printers.length === 0) {
    return { success: false, error: 'No printers detected' };
  }

  return new Promise((resolve) => {
    const body = JSON.stringify({
      agentId,
      hostname: require('os').hostname(),
      platform: process.platform,
      printers: printers.printers,
    });

    const url = new URL(config.backendUrl + '/api/agent/auto-register');
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + config.agentSecret,
        'X-Agent-ID': agentId,
        'Content-Length': Buffer.byteLength(body),
      },
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          if (result.success) {
            config.stations = result.data.stations;
            config.agentId = agentId;
            saveConfig();
          }
          resolve(result);
        } catch {
          resolve({ success: false, error: data });
        }
      });
    });

    req.on('error', (e) => {
      resolve({ success: false, error: e.message });
    });

    req.write(body);
    req.end();
  });
}

// Start agent
function startAgent() {
  if (agentProcess) {
    agentProcess.kill();
  }

  if (!config.stations || config.stations.length === 0) {
    return { success: false, error: 'No stations configured' };
  }

  const station = config.stations[0];
  const args = [
    '-m', 'nexino_agent', 'start',
    '--station-id', station.stationId,
    '--agent-id', config.agentId,
    '--backend-url', config.backendUrl,
  ];

  agentProcess = spawn('python', args, {
    cwd: path.join(__dirname, '..'),
    shell: true,
    env: { ...process.env, PYTHONPATH: path.join(__dirname, '..') },
  });

  agentProcess.stdout.on('data', (d) => {
    console.log('[AGENT]', d.toString().trim());
  });

  agentProcess.stderr.on('data', (d) => {
    console.log('[AGENT]', d.toString().trim());
  });

  agentProcess.on('close', (code) => {
    console.log('[AGENT] Stopped with code', code);
    agentProcess = null;
  });

  return { success: true, pid: agentProcess.pid };
}

// Stop agent
function stopAgent() {
  if (agentProcess) {
    agentProcess.kill();
    agentProcess = null;
    return { success: true };
  }
  return { success: false, error: 'No agent running' };
}

// HTTP Server
const server = http.createServer(async (req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  // API Routes
  if (url.pathname === '/api/detect' && req.method === 'GET') {
    const result = await detectPrinters();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result));
    return;
  }

  if (url.pathname === '/api/register' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', async () => {
      try {
        const { agentId } = JSON.parse(body);
        const result = await registerStations(agentId);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: e.message }));
      }
    });
    return;
  }

  if (url.pathname === '/api/start' && req.method === 'POST') {
    const result = startAgent();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result));
    return;
  }

  if (url.pathname === '/api/stop' && req.method === 'POST') {
    const result = stopAgent();
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result));
    return;
  }

  if (url.pathname === '/api/status' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      running: agentProcess !== null,
      pid: agentProcess ? agentProcess.pid : null,
      config,
    }));
    return;
  }

  if (url.pathname === '/api/config' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(config));
    return;
  }

  if (url.pathname === '/api/config' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      try {
        const updates = JSON.parse(body);
        config = { ...config, ...updates };
        saveConfig();
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true }));
      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: e.message }));
      }
    });
    return;
  }

  if (url.pathname === '/api/stations' && req.method === 'GET') {
    const agentId = url.searchParams.get('agentId');
    const stations = agentId
      ? config.stations.filter(s => s.agentId === agentId || !s.agentId)
      : config.stations;
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ stations }));
    return;
  }

  // Serve GUI
  let filePath = url.pathname === '/' ? '/index.html' : url.pathname;
  filePath = path.join(__dirname, filePath);

  const ext = path.extname(filePath);
  const contentTypes = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
  };

  try {
    const content = fs.readFileSync(filePath);
    res.writeHead(200, { 'Content-Type': contentTypes[ext] || 'text/plain' });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end('Not found');
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n╔══════════════════════════════════════════╗`);
  console.log(`║   Nexino Print Agent Control Panel      ║`);
  console.log(`║   http://localhost:${PORT}                ║`);
  console.log(`╚══════════════════════════════════════════╝\n`);
  console.log('Open the URL above in your browser to manage the agent.\n');
});
