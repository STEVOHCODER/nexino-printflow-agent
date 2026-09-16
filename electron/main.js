const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const { autoUpdater } = require('electron-updater');
const Store = require('electron-store');
const fs = require('fs');

const isProd = app.isPackaged;
const appDir = isProd
  ? path.join(process.resourcesPath, '..', '..')
  : path.join(__dirname, '..');
const agentRoot = isProd
  ? path.join(process.resourcesPath)
  : path.join(__dirname, '..');

// Bundled Python path (Inno Setup installs it next to the app)
const bundledPython = path.join(appDir, 'python', 'python.exe');
const bundledAgent = path.join(appDir, 'agent');

function getPythonPath() {
  // Use bundled Python if it exists (Inno Setup install)
  if (fs.existsSync(bundledPython)) return bundledPython;
  // Fall back to system Python
  return 'python';
}

function getAgentRoot() {
  // Use bundled agent if it exists (Inno Setup install)
  if (fs.existsSync(bundledAgent)) return bundledAgent;
  // Fall back to original agentRoot
  return agentRoot;
}

// Configure auto-updater
autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = true;
autoUpdater.logger = {
  info: (msg) => console.log('[Updater]', msg),
  warn: (msg) => console.warn('[Updater]', msg),
  error: (msg) => console.error('[Updater]', msg),
};

const store = new Store({
  defaults: {
    backendUrl: 'https://backend-mauve-delta-32.vercel.app',
    agentId: 'AGENT-001',
    agentSecret: 'nexino-printflow-agent-secret-2026',
    stations: [],
    printers: [],
    autoStart: false,
  }
});

let mainWindow;
let agentProcess = null;

// ==================== DEPENDENCY CHECK ====================

function checkPython() {
  try {
    execSync(`"${getPythonPath()}" --version`, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function installDependencies(mainWindow) {
  return new Promise((resolve, reject) => {
    const reqFile = path.join(agentRoot, 'requirements.txt');
    if (!fs.existsSync(reqFile)) {
      resolve({ success: true, message: 'No requirements.txt found' });
      return;
    }

    if (mainWindow) {
      mainWindow.webContents.send('agent-log', '[Setup] Installing Python dependencies...\n');
    }

    const pip = spawn(getPythonPath(), ['-m', 'pip', 'install', '-r', reqFile, '--quiet'], {
      cwd: getAgentRoot(),
      shell: true,
      env: { ...process.env, PYTHONPATH: agentRoot }
    });

    let output = '';
    pip.stdout.on('data', (d) => { output += d.toString(); });
    pip.stderr.on('data', (d) => { output += d.toString(); });

    pip.on('close', (code) => {
      if (code === 0) {
        if (mainWindow) {
          mainWindow.webContents.send('agent-log', '[Setup] Dependencies installed successfully.\n');
        }
        resolve({ success: true });
      } else {
        reject(new Error(`pip install failed (exit ${code}): ${output}`));
      }
    });
  });
}

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

  // Check Python and install dependencies on first run
  mainWindow.webContents.on('did-finish-load', async () => {
    if (!checkPython()) {
      mainWindow.webContents.send('agent-log', '[Error] Python is not installed or not in PATH.\n');
      mainWindow.webContents.send('agent-log', '[Error] Please install Python 3.10+ from https://python.org\n');
      dialog.showMessageBox(mainWindow, {
        type: 'error',
        title: 'Python Not Found',
        message: 'Python 3.10+ is required but not installed.',
        detail: 'Please install Python from https://python.org and make sure "Add Python to PATH" is checked during installation.',
        buttons: ['Open Python Website', 'Exit'],
      }).then(({ response }) => {
        if (response === 0) shell.openExternal('https://www.python.org/downloads/');
        app.quit();
      });
      return;
    }

    try {
      await installDependencies(mainWindow);
    } catch (err) {
      mainWindow.webContents.send('agent-log', `[Error] Failed to install dependencies: ${err.message}\n`);
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Check for updates after window is ready
  if (isProd) {
    setTimeout(() => {
      checkForUpdates();
    }, 3000);
  }
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  killAgent();
  app.quit();
});

app.on('before-quit', () => {
  killAgent();
});

function killAgent() {
  if (agentProcess) {
    try {
      // Kill the process tree on Windows (agent may spawn child processes)
      const { execSync } = require('child_process');
      if (process.platform === 'win32') {
        try { execSync(`taskkill /PID ${agentProcess.pid} /T /F`, { stdio: 'ignore' }); } catch {}
      }
      agentProcess.kill();
    } catch {}
    agentProcess = null;
  }
}

// ==================== AUTO-UPDATE ====================

function checkForUpdates() {
  autoUpdater.checkForUpdates().catch((err) => {
    console.error('Update check failed:', err.message);
  });
}

autoUpdater.on('checking-for-update', () => {
  sendUpdateStatus('checking');
});

autoUpdater.on('update-available', (info) => {
  sendUpdateStatus('available', {
    version: info.version,
    releaseNotes: info.releaseNotes,
  });

  // Prompt user to download
  dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Update Available',
    message: `A new version (v${info.version}) is available.`,
    detail: 'Would you like to download and install it now? The app will restart automatically.',
    buttons: ['Download & Install', 'Later'],
    defaultId: 0,
    cancelId: 1,
  }).then(({ response }) => {
    if (response === 0) {
      sendUpdateStatus('downloading');
      autoUpdater.downloadUpdate();
    }
  });
});

autoUpdater.on('update-not-available', () => {
  sendUpdateStatus('up-to-date');
});

autoUpdater.on('download-progress', (progress) => {
  sendUpdateStatus('downloading', {
    percent: Math.round(progress.percent),
    transferred: progress.transferred,
    total: progress.total,
  });
});

autoUpdater.on('update-downloaded', (info) => {
  sendUpdateStatus('downloaded', { version: info.version });

  dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Update Ready',
    message: `Version ${info.version} has been downloaded.`,
    detail: 'The app will restart to apply the update. Save any unsaved work.',
    buttons: ['Restart Now', 'Later'],
    defaultId: 0,
    cancelId: 1,
  }).then(({ response }) => {
    if (response === 0) {
      autoUpdater.quitAndInstall();
    }
  });
});

autoUpdater.on('error', (err) => {
  sendUpdateStatus('error', { message: err.message });
});

function sendUpdateStatus(status, data = {}) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update-status', { status, ...data });
  }
}

// ==================== IPC HANDLERS ====================

ipcMain.handle('check-dependencies', async () => {
  const pythonOk = checkPython();
  if (!pythonOk) {
    return { success: false, error: 'Python is not installed or not in PATH' };
  }
  try {
    await installDependencies(mainWindow);
    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('get-config', () => {
  return store.store;
});

ipcMain.handle('save-config', (event, config) => {
  store.set(config);
  return { success: true };
});

ipcMain.handle('check-for-updates', () => {
  if (isProd) {
    checkForUpdates();
    return { success: true };
  }
  return { success: false, error: 'Auto-update only available in production builds' };
});

ipcMain.handle('install-update', () => {
  autoUpdater.quitAndInstall();
  return { success: true };
});

ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.handle('detect-printers', async () => {
  return new Promise((resolve) => {
    const python = spawn(getPythonPath(), ['-m', 'nexino_agent', 'detect'], {
      cwd: getAgentRoot(),
      shell: true,
      env: { ...process.env, PYTHONPATH: getAgentRoot() }
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

    const python = spawn(getPythonPath(), args, {
      cwd: getAgentRoot(),
      shell: true,
      env: { ...process.env, PYTHONPATH: getAgentRoot() }
    });

    let output = '';
    python.stdout.on('data', (data) => { output += data.toString(); });
    python.stderr.on('data', (data) => { output += data.toString(); });
    python.on('close', (code) => {
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

  agentProcess = spawn(getPythonPath(), args, {
    cwd: getAgentRoot(),
    shell: true,
    env: { ...process.env, PYTHONPATH: getAgentRoot() }
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
