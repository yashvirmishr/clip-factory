'use strict'

/**
 * Clip Factory desktop shell.
 *
 * Responsibilities, in order of importance:
 *   1. own the Python sidecar's lifetime (spawn, health-check, hard kill)
 *   2. show one window pointed at it
 *   3. never leave an orphan python.exe behind
 *
 * The renderer holds no privileges: no node integration, context isolation on,
 * sandboxed, and navigation confined to the sidecar origin.
 */

const { app, BrowserWindow, dialog, shell } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..')
const isDebug = process.argv.includes('--debug')

let sidecar = null
let mainWindow = null

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

function pythonExecutable() {
  const candidates =
    process.platform === 'win32'
      ? [path.join(ROOT, '.venv', 'Scripts', 'python.exe')]
      : [path.join(ROOT, '.venv', 'bin', 'python')]
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function killSidecar() {
  const child = sidecar
  sidecar = null
  if (!child || child.killed || !child.pid) return
  try {
    if (process.platform === 'win32') {
      // /T kills the whole tree: uvicorn can hold worker children.
      spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true })
    } else {
      child.kill('SIGTERM')
    }
  } catch {
    /* already gone */
  }
}

async function waitForHealth(url, child, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs
  let stderr = ''
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString()
    if (stderr.length > 8000) stderr = stderr.slice(-8000)
  })
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(
        `Sidecar exited early (code ${child.exitCode}).\n\n${stderr.slice(-1200)}`,
      )
    }
    try {
      const response = await fetch(`${url}/api/health`)
      if (response.ok) return
    } catch {
      /* not listening yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 350))
  }
  throw new Error(
    `Sidecar did not become healthy within ${timeoutMs} ms.\n\n${stderr.slice(-1200)}`,
  )
}

async function startSidecar() {
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const python = pythonExecutable()

  sidecar = spawn(python, ['-m', 'clipper', '--port', String(port)], {
    cwd: ROOT,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONPATH: [path.join(ROOT, 'backend'), process.env.PYTHONPATH || '']
        .filter(Boolean)
        .join(path.delimiter),
      CLIPPER_DATA_DIR: app.getPath('userData'),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  sidecar.on('error', (error) => {
    console.error('sidecar spawn failed:', error.message)
  })
  sidecar.stdout.on('data', (chunk) => {
    if (isDebug) process.stdout.write(`[sidecar] ${chunk}`)
  })

  await waitForHealth(url, sidecar)
  console.log(`Clip Factory sidecar ready at ${url}`)
  return url
}

function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1080,
    minHeight: 680,
    show: false,
    backgroundColor: '#0a0a0b',
    title: 'Clip Factory',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      backgroundThrottling: true,
    },
  })

  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // Keep the window inside the app; send anything else to the real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (!target.startsWith(url)) shell.openExternal(target)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (!target.startsWith(url)) {
      event.preventDefault()
      shell.openExternal(target)
    }
  })

  mainWindow.loadURL(url)
}

const gotLock = app.requestSingleInstanceLock()

if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app
    .whenReady()
    .then(async () => {
      try {
        const url = await startSidecar()
        createWindow(url)
      } catch (error) {
        dialog.showErrorBox(
          'Clip Factory could not start',
          `${error.message}\n\nCheck that .venv exists at the project root and that ffmpeg is on PATH.`,
        )
        killSidecar()
        app.quit()
      }
    })
    .catch((error) => {
      dialog.showErrorBox('Clip Factory failed', String(error))
      app.quit()
    })

  app.on('window-all-closed', () => app.quit())
  app.on('will-quit', () => killSidecar())
  process.on('exit', () => killSidecar())
}
