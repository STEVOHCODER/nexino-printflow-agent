const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const Store = require('electron-store');

const store = new Store({
  defaults: {
    backendUrl: 'https://nexino-printflow-api.vercel.app',
    agentId: 'AGENT-001',
    agentSecret: 'nexino-printflow-agent-secret-2026',
    stations: [],
    printers: [],
    autoStart: false,
  }
});

let mainWindow;
let agentProcess = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    title: 'Nexino Print Agent',
    backgroundColor: '#f8fafc',
    autoHideMenuBar: true,
  });

  mainWindow.loadFile('index.html');

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (agentProcess) {
    agentProcess.kill();
  }
  app.quit();
});

// IPC Handlers
ipcMain.handle('get-config', () => {
  return store.store;
});

ipcMain.handle('save-config', (event, config) => {
  store.set(config);
  return { success: true };
});

ipcMain.handle('detect-printers', async () => {
  return new Promise((resolve) => {
    const python = spawn('python', ['-m', 'nexino_agent', 'detect'], {
      cwd: path.join(__dirname, '..'),
      shell: true,
      env: { ...process.env, PYTHONPATH: path.join(__dirname, '..') }
    });

    let output = '';
    python.stdout.on('data', (data) => { output += data.toString(); });
    python.stderr.on('data', (data) => { output += data.toString(); });
    python.on('close', () => {
      try {
        const printers = JSON.parse(output);
        store.set('printers', printers);
        resolve({ success: true, printers });
      } catch {
        resolve({ success: false, error: output, printers: [] });
      }
    });
  });
});

ipcMain.handle('register-stations', async (event, { agentId, backendUrl, agentSecret }) => {
  return new Promise((resolve) => {
    const args = [
      '-m', 'nexino_agent', 'register',
      '--agent-id', agentId,
      '--backend-url', backendUrl,
      '--yes',
    ];

    const python = spawn('python', args, {
      cwd: path.join(__dirname, '..'),
      shell: true,
      env: { ...process.env, PYTHONPATH: path.join(__dirname, '..') }
    });

    let output = '';
    python.stdout.on('data', (data) => { output += data.toString(); });
    python.stderr.on('data', (data) => { output += data.toString(); });
    python.on('close', (code) => {
      // Parse JSON_RESULT from output
      try {
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('JSON_RESULT:')) {
            const result = JSON.parse(line.substring(12));
            if (result.stations) {
              store.set('stations', result.stations);
            }
            resolve({ success: result.success !== false, stations: result.stations || [], output });
            return;
          }
        }
      } catch {}

      resolve({ success: code === 0, output });
    });
  });
});

ipcMain.handle('start-agent', async (event, { stationId, agentId, backendUrl }) => {
  if (agentProcess) {
    agentProcess.kill();
  }

  const args = [
    '-m', 'nexino_agent', 'start',
    '--agent-id', agentId,
    '--backend-url', backendUrl,
  ];

  if (stationId) {
    args.push('--station-id', stationId);
  }

  agentProcess = spawn('python', args, {
    cwd: path.join(__dirname, '..'),
    shell: true,
    env: { ...process.env, PYTHONPATH: path.join(__dirname, '..') }
  });

  agentProcess.stdout.on('data', (data) => {
    if (mainWindow) {
      mainWindow.webContents.send('agent-log', data.toString());
    }
  });

  agentProcess.stderr.on('data', (data) => {
    if (mainWindow) {
      mainWindow.webContents.send('agent-log', data.toString());
    }
  });

  agentProcess.on('close', (code) => {
    if (mainWindow) {
      mainWindow.webContents.send('agent-stopped', code);
    }
    agentProcess = null;
  });

  return { success: true, pid: agentProcess.pid };
});

ipcMain.handle('stop-agent', async () => {
  if (agentProcess) {
    agentProcess.kill();
    agentProcess = null;
    return { success: true };
  }
  return { success: false, error: 'No agent running' };
});

ipcMain.handle('get-agent-status', () => {
  return {
    running: agentProcess !== null,
    pid: agentProcess ? agentProcess.pid : null,
  };
});

ipcMain.handle('open-external', (event, url) => {
  shell.openExternal(url);
});

ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  });
  return result.filePaths[0] || null;
});
