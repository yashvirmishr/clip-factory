'use strict'

const { contextBridge, ipcRenderer } = require('electron')

// Intentionally tiny. The renderer talks to the sidecar over localhost HTTP;
// this bridge only exposes facts the UI cannot get from the browser.
contextBridge.exposeInMainWorld('clipFactory', {
  desktop: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
  copyText: (text) => ipcRenderer.invoke('clipboard:write', text),
  // Opens a folder inside the app data directory. Main refuses anything else.
  openPath: (target) => ipcRenderer.invoke('clip-factory:open-path', String(target)),
})
