'use strict'

const { contextBridge } = require('electron')

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
})
