'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain } = require('electron');
const path  = require('path');
const http  = require('http');
const fs    = require('fs');
const { spawn } = require('child_process');

const ROOT   = path.join(__dirname, '..');
const isDev  = process.argv.includes('--dev');
const PORT   = parseInt(process.env.ANCHOR_PORT || '3000', 10);

let mainWindow   = null;
let tray         = null;
let serverProcess = null;

// ── Server ──────────────────────────────────────────────────────────

function startServer() {
  return new Promise((resolve, reject) => {
    const serverScript = path.join(ROOT, 'mcp', 'server.cjs');

    serverProcess = spawn(process.execPath, [serverScript], {
      cwd: ROOT,
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', ANCHOR_PORT: String(PORT), ANCHOR_FRESH_START: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    serverProcess.stdout.on('data', d => process.stdout.write('[server] ' + d));
    serverProcess.stderr.on('data', d => process.stderr.write('[server:err] ' + d));
    serverProcess.on('error', reject);
    serverProcess.on('exit', (code) => {
      if (code !== 0 && code !== null) {
        console.error('[server] exited with code', code);
      }
    });

    waitForPort(PORT, 30_000).then(resolve).catch(reject);
  });
}

function waitForPort(port, timeout) {
  const deadline = Date.now() + timeout;
  return new Promise((resolve, reject) => {
    function attempt() {
      if (Date.now() > deadline) {
        return reject(new Error(`Server did not respond on port ${port} within ${timeout}ms`));
      }
      const req = http.get(`http://localhost:${port}/`, res => {
        res.destroy();
        resolve();
      });
      req.on('error', () => setTimeout(attempt, 400));
      req.setTimeout(600, () => { req.destroy(); setTimeout(attempt, 400); });
    }
    attempt();
  });
}

function stopServer() {
  if (!serverProcess || serverProcess.killed) return;
  // Graceful: ask the server to shut down
  http.request(
    { hostname: 'localhost', port: PORT, path: '/shutdown', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': '2' } },
    () => {}
  ).on('error', () => {}).end('{}');
  // Force-kill after 3 s
  setTimeout(() => {
    if (!serverProcess.killed) serverProcess.kill('SIGTERM');
  }, 3000);
}

// ── Window state persistence ────────────────────────────────────────

const STATE_PATH = path.join(ROOT, 'logs', 'runtime', 'window-state.json');

function loadWindowState() {
  try { return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); }
  catch { return { width: 1360, height: 860 }; }
}

function saveWindowState(win) {
  if (!win || win.isDestroyed()) return;
  const b = win.getBounds();
  try {
    fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
    fs.writeFileSync(STATE_PATH, JSON.stringify({
      ...b, isMaximized: win.isMaximized()
    }));
  } catch {}
}

// ── BrowserWindow ───────────────────────────────────────────────────

function createWindow() {
  const state = loadWindowState();

  mainWindow = new BrowserWindow({
    width:     state.width  || 1360,
    height:    state.height || 860,
    x:         state.x,
    y:         state.y,
    minWidth:  900,
    minHeight: 600,
    title:     'Loom',
    icon:      resolveIcon(),
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      // Allow localhost content to work normally
      webSecurity:      true,
    },
    backgroundColor: '#eef5ff',
    show: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
  });

  if (state.isMaximized) mainWindow.maximize();

  mainWindow.loadURL(`http://localhost:${PORT}`);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools();
  });

  // Minimize to tray on close (Windows/Linux)
  mainWindow.on('close', e => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      if (process.platform === 'win32') {
        tray && tray.displayBalloon({
          iconType: 'info',
          title: 'Loom',
          content: 'Loom is still running. Right-click the tray icon to quit.',
        });
      }
    }
    saveWindowState(mainWindow);
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  // Open external links in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(`http://localhost:${PORT}`)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  mainWindow.on('resize', () => saveWindowState(mainWindow));
  mainWindow.on('move',   () => saveWindowState(mainWindow));
}

// ── Tray ────────────────────────────────────────────────────────────

function createTray() {
  const icon = resolveIcon(16);
  tray = new Tray(icon);
  tray.setToolTip('Loom — AI Workspace');

  const menu = Menu.buildFromTemplate([
    {
      label: 'Open Loom',
      click: () => {
        if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
        else createWindow();
      }
    },
    {
      label: 'Open in Browser',
      click: () => shell.openExternal(`http://localhost:${PORT}`)
    },
    { type: 'separator' },
    {
      label: 'Quit Loom',
      click: () => { app.isQuitting = true; app.quit(); }
    },
  ]);

  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.focus() : mainWindow.show();
    } else {
      createWindow();
    }
  });
  tray.on('double-click', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
    else createWindow();
  });
}

// ── App menu ────────────────────────────────────────────────────────

function buildMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'New File',
          accelerator: 'CmdOrCtrl+N',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('workspace-new-file')?.click()`
          )
        },
        {
          label: 'New Folder',
          accelerator: 'CmdOrCtrl+Shift+N',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('workspace-new-folder')?.click()`
          )
        },
        { type: 'separator' },
        {
          label: 'Quit',
          accelerator: process.platform === 'darwin' ? 'Cmd+Q' : 'Alt+F4',
          click: () => { app.isQuitting = true; app.quit(); }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        ...(isDev ? [{ type: 'separator' }, { role: 'toggleDevTools' }] : [])
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Open in Browser',
          click: () => shell.openExternal(`http://localhost:${PORT}`)
        },
        {
          label: 'About Loom',
          click: () => dialog.showMessageBox(mainWindow, {
            title: 'About Loom',
            message: 'Loom — AI-native Workspace',
            detail: `Version ${app.getVersion()}\nElectron ${process.versions.electron}\nNode ${process.versions.node}`,
            buttons: ['OK'],
            icon: resolveIcon(),
          })
        }
      ]
    }
  ];

  if (process.platform === 'darwin') {
    template.unshift({
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    });
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── Icon helper ─────────────────────────────────────────────────────

function resolveIcon(size) {
  const candidates = [
    path.join(ROOT, 'resource', 'assets', 'icon.ico'),
    path.join(ROOT, 'resource', 'assets', 'icon.png'),
    path.join(ROOT, 'resource', 'assets', 'logo-mark.png'),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      const img = nativeImage.createFromPath(p);
      return size ? img.resize({ width: size, height: size }) : img;
    }
  }
  return nativeImage.createEmpty();
}

// ── Lifecycle ───────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Single instance lock
  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return;
  }

  buildMenu();
  createTray();

  // Splash: show loading dialog while server boots
  console.log('[loom] Starting Anchor server…');
  try {
    await startServer();
    console.log('[loom] Server ready on port', PORT);
  } catch (err) {
    await dialog.showErrorBox(
      'Loom — Failed to Start',
      `The Anchor server did not start:\n\n${err.message}\n\nCheck that Node.js is installed and bridge/node_modules is present.`
    );
    app.quit();
    return;
  }

  createWindow();
});

// Focus existing window if a second instance is launched
app.on('second-instance', () => {
  if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
});

app.on('window-all-closed', () => {
  // Stay alive in tray on Windows/Linux; quit on macOS
  if (process.platform === 'darwin') { app.isQuitting = true; app.quit(); }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  stopServer();
});
