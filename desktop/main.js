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

const { app, BrowserWindow, clipboard, dialog, ipcMain, screen, shell } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')

// Packaged builds keep the backend, built UI and Python runtime beside the
// executable in resources/; a checkout keeps them at the repository root.
const ROOT = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..')
const isDebug = process.env.CLIP_FACTORY_DEBUG === '1'

let sidecar = null
let mainWindow = null

// Window placement is a preference like any other: a second launch should open
// where the last one was left, not at a hard-coded size that is too small on a
// 4K desk. Bounds are clamped to a real display so unplugging a monitor cannot
// strand the window off-screen.
function windowStatePath() {
  return path.join(app.getPath('userData'), 'window.json')
}

function readWindowState() {
  try {
    const raw = JSON.parse(fs.readFileSync(windowStatePath(), 'utf8'))
    if (!Number.isFinite(raw.width) || !Number.isFinite(raw.height)) return null
    return raw
  } catch {
    return null
  }
}

function onVisibleDisplay(bounds) {
  const area = { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height }
  return screen.getAllDisplays().some((display) => {
    const overlapX = Math.max(0, Math.min(area.x + area.width, display.bounds.x + display.bounds.width) - Math.max(area.x, display.bounds.x))
    const overlapY = Math.max(0, Math.min(area.y + area.height, display.bounds.y + display.bounds.height) - Math.max(area.y, display.bounds.y))
    return overlapX >= 160 && overlapY >= 120
  })
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const maximized = mainWindow.isMaximized()
  const bounds = maximized ? mainWindow.getNormalBounds() : mainWindow.getBounds()
  try {
    fs.writeFileSync(windowStatePath(), JSON.stringify({ ...bounds, maximized }))
  } catch {
    /* a lost preference is not worth interrupting the session */
  }
}

// Write-only clipboard bridge. The renderer stays sandboxed and privileged
// modules stay in the main process; this is only used by "Copy diagnostics".
ipcMain.handle('clipboard:write', (_event, text) => {
  if (typeof text !== 'string') return false
  clipboard.writeText(text.slice(0, 200_000))
  return true
})

// Setup's "Open folder" button. The renderer passes a path from the sidecar;
// resolving it against the app data root is what keeps this from becoming a
// general "open anything on disk" bridge.
ipcMain.handle('clip-factory:open-path', async (_event, target) => {
  const root = path.resolve(app.getPath('userData'))
  const resolved = path.resolve(String(target || ''))
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    return { ok: false, error: 'That folder is outside the app data folder.' }
  }
  try {
    await fs.promises.mkdir(resolved, { recursive: true })
    const problem = await shell.openPath(resolved)
    return problem ? { ok: false, error: problem } : { ok: true, error: '' }
  } catch (error) {
    return { ok: false, error: String(error.message || error) }
  }
})

const DEFAULT_PORT = 8756

// The OAuth callback is registered once, against a fixed loopback URL, so the
// sidecar cannot move to a random port on every launch. CLIP_FACTORY_PORT
// exists for a machine where 8756 is taken; whatever it is, the Accounts tab
// shows the same URI the provider must be configured with.
function preferredPort() {
  const raw = Number(process.env.CLIP_FACTORY_PORT || '')
  return Number.isInteger(raw) && raw > 0 && raw < 65536 ? raw : DEFAULT_PORT
}

function portIsFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    server.once('error', () => resolve(false))
    server.listen(port, '127.0.0.1', () => {
      server.close(() => resolve(true))
    })
  })
}

function pythonExecutable() {
  const onWindows = process.platform === 'win32'
  const candidates = []
  if (app.isPackaged) {
    candidates.push(
      onWindows
        ? path.join(ROOT, 'python', 'python.exe')
        : path.join(ROOT, 'python', 'bin', 'python3'),
    )
  }
  candidates.push(
    onWindows
      ? path.join(ROOT, '.venv', 'Scripts', 'python.exe')
      : path.join(ROOT, '.venv', 'bin', 'python'),
  )
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  return onWindows ? 'python' : 'python3'
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
  const port = preferredPort()
  if (!(await portIsFree(port))) {
    throw new Error(
      `Port ${port} is already in use, and the publishing callback is tied to it.` +
        ` Close the app using that port, or start Clip Factory with CLIP_FACTORY_PORT set to a free one.`,
    )
  }
  const url = `http://127.0.0.1:${port}`
  const python = pythonExecutable()

  // The packaged runtime is an embeddable Python whose ._pth isolates it from
  // PYTHONPATH, so point it at the bundled backend explicitly. A checkout keeps
  // using the normal module entry point.
  const backendDir = path.join(ROOT, 'backend')
  const bootstrap = app.isPackaged
    ? [
        '-c',
        `import sys; sys.path.insert(0, ${JSON.stringify(backendDir)}); from clipper.__main__ import main; main()`,
        '--port',
        String(port),
      ]
    : ['-m', 'clipper', '--port', String(port)]

  sidecar = spawn(python, bootstrap, {
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
  const saved = readWindowState()
  const placement =
    saved && onVisibleDisplay(saved)
      ? { width: Math.max(1200, saved.width), height: Math.max(720, saved.height), x: saved.x, y: saved.y }
      : { width: 1600, height: 1000 }

  mainWindow = new BrowserWindow({
    ...placement,
    minWidth: 1200,
    minHeight: 720,
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

  mainWindow.once('ready-to-show', () => {
    if (saved && saved.maximized) mainWindow.maximize()
    mainWindow.show()
  })

  // Debounced so dragging an edge does not write a file per pixel.
  let saveTimer = null
  const queueSave = () => {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(saveWindowState, 400)
  }
  mainWindow.on('resize', queueSave)
  mainWindow.on('move', queueSave)
  mainWindow.on('maximize', queueSave)
  mainWindow.on('unmaximize', queueSave)
  mainWindow.on('close', saveWindowState)
  mainWindow.on('closed', () => {
    clearTimeout(saveTimer)
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
        const hint = /^Port \d+/.test(error.message)
          ? ''
          : '\n\nCheck that .venv exists at the project root and that ffmpeg is on PATH.'
        dialog.showErrorBox('Clip Factory could not start', `${error.message}${hint}`)
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
