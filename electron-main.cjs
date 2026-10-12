const { app, BrowserWindow, shell } = require('electron');

const APP_PORT = process.env.VITE_PORT || process.env.PORT || '8000';
const APP_URL =
  process.env.FORGE_DESKTOP_URL ||
  process.env.VITE_DEV_SERVER_URL ||
  `http://localhost:${APP_PORT}`;
const APP_ORIGIN = new URL(APP_URL).origin;

function openExternalUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:';
  } catch {
    return false;
  }
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    backgroundColor: '#070a0f',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (openExternalUrl(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    let isAppOrigin = false;
    try {
      isAppOrigin = new URL(url).origin === APP_ORIGIN;
    } catch {
      // Block malformed and non-HTTP navigation targets.
    }
    if (!isAppOrigin) {
      event.preventDefault();
      if (openExternalUrl(url)) void shell.openExternal(url);
    }
  });

  void mainWindow.loadURL(APP_URL);
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
