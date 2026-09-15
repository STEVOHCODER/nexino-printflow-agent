const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (config) => ipcRenderer.invoke('save-config', config),
  detectPrinters: () => ipcRenderer.invoke('detect-printers'),
  registerStations: (data) => ipcRenderer.invoke('register-stations', data),
  startAgent: (data) => ipcRenderer.invoke('start-agent', data),
  stopAgent: () => ipcRenderer.invoke('stop-agent'),
  getAgentStatus: () => ipcRenderer.invoke('get-agent-status'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  onAgentLog: (callback) => ipcRenderer.on('agent-log', (event, data) => callback(data)),
  onAgentStopped: (callback) => ipcRenderer.on('agent-stopped', (event, code) => callback(code)),

  // Auto-update
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  onUpdateStatus: (callback) => ipcRenderer.on('update-status', (event, data) => callback(data)),
});
