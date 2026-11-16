"use strict";
/**
 * Yoraito desktop shell (Electron main process). The same file for every tool: everything that differs
 * between tools is in tool.json next to this file (see PLACEHOLDERS.md).
 *
 * What it does, in order:
 *   1. makes sure only one copy of this tool is running (each tool has its own lock);
 *   2. starts the bundled Python backend on 127.0.0.1, on the tool's fixed port or a free one;
 *   3. waits for the backend's health route, then shows the interface the backend serves;
 *   4. asks the backend to stop when the app closes (and ends it if it doesn't), and tells the user if the
 *      backend stops by itself.
 *
 * Privacy: the window may only talk to its own backend on 127.0.0.1. Every other request is cancelled. Links the
 * tool lists in tool.json "externalLinks" open in the user's own browser, and only when the page asks.
 */
const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const HOST = "127.0.0.1";
const HEALTH_TIMEOUT_MS = 60_000;
const SHUTDOWN_WAIT_MS = 5_000;

const tool = loadTool();
// The same layout as yoraito-core's paths: YORAITO_HOME (default ~/.yoraito), one folder per tool.
const dataDir = path.join(process.env.YORAITO_HOME || path.join(os.homedir(), ".yoraito"), tool.id);
const logDir = path.join(dataDir, "logs");
fs.mkdirSync(logDir, { recursive: true });
// Chromium's profile, and with it the single-instance lock, is per tool, so two Yoraito tools can run at once.
app.setPath("userData", path.join(dataDir, "electron"));

const loadingPage = path.join(__dirname, "loading.html");
const loadingUrl = pathToFileURL(loadingPage).href;
const shutdownToken = crypto.randomBytes(24).toString("hex");

let backend = null; // the child process
let backendPort = 0;
let mainWindow = null;
let quitting = false;
let stopping = false;

function loadTool() {
  const raw = JSON.parse(fs.readFileSync(path.join(__dirname, "tool.json"), "utf8"));
  if (!/^[a-z0-9][a-z0-9-]*$/.test(raw.id || "")) throw new Error('tool.json: "id" must be lowercase letters, digits and hyphens');
  if (!raw.name) throw new Error('tool.json: "name" is required');
  const port = Number(raw.port || 0);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('tool.json: "port" must be 0 or a port number');
  const links = (raw.externalLinks || []).map(String);
  if (links.some((link) => !link.startsWith("https://"))) throw new Error('tool.json: "externalLinks" must be https:// URLs');
  return {
    id: raw.id,
    name: raw.name,
    port,
    healthPath: raw.healthPath || "/api/health",
    externalLinks: links,
    crashMessage: raw.crashMessage || "Your data on this computer is safe.",
  };
}

function log(message) {
  try {
    fs.appendFileSync(path.join(logDir, "desktop.log"), `${new Date().toISOString()} ${message}\n`);
  } catch {
    /* logging must never stop the app */
  }
}

// ---- one instance of this tool only -----------------------------------------------------------------------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(start).catch((err) => fatal(`${tool.name} could not start.\n\n${err && err.message ? err.message : err}`));
}

// ---- backend ----------------------------------------------------------------------------------------------
function backendExecutable() {
  const name = `${tool.id}-backend`;
  const exe = process.platform === "win32" ? `${name}.exe` : name;
  const base = app.isPackaged ? path.join(process.resourcesPath, "backend") : path.join(__dirname, "stage", "backend");
  return path.join(base, name, exe);
}

function portIsFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, HOST, () => server.close(() => resolve(true)));
  });
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, HOST, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function choosePort() {
  if (!tool.port) return freePort();
  // A fixed port: workbooks, AI client settings or registered sign-in addresses point at it.
  if (!(await portIsFree(tool.port))) {
    throw new Error(`Port ${tool.port} is in use by another program, and ${tool.name} needs that port.\n` +
      "Close the other program (or the copy of this tool started outside the desktop app) and try again.");
  }
  return tool.port;
}

function startBackend(port) {
  const exe = backendExecutable();
  if (!fs.existsSync(exe)) throw new Error(`The ${tool.name} engine is missing:\n${exe}`);
  const out = fs.openSync(path.join(logDir, "backend-output.log"), "a");
  backend = spawn(exe, [], {
    cwd: path.dirname(exe),
    windowsHide: true,
    stdio: ["ignore", out, out],
    env: {
      ...process.env,
      YORAITO_DESKTOP: "1",
      YORAITO_PORT: String(port),
      YORAITO_DATA_DIR: dataDir,
      YORAITO_PARENT_PID: String(process.pid),
      YORAITO_SHUTDOWN_TOKEN: shutdownToken,
    },
  });
  log(`backend started pid=${backend.pid} port=${port}`);
  backend.on("exit", (code, signal) => {
    log(`backend exited code=${code} signal=${signal}`);
    backend = null;
    if (!quitting) onBackendLost(code);
  });
}

function forceStop() {
  if (!backend) return;
  const pid = backend.pid;
  try {
    if (process.platform === "win32") {
      // /T also ends anything the backend started; /F because it has no console to receive a polite request.
      spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
    } else {
      process.kill(pid, "SIGKILL");
    }
  } catch (err) {
    log(`forceStop: ${err.message}`);
  }
  log(`backend force-stopped pid=${pid}`);
}

function askBackendToStop() {
  return new Promise((resolve) => {
    const req = http.request(
      { host: HOST, port: backendPort, path: "/__desktop/shutdown", method: "POST", timeout: 2000,
        headers: { "X-Yoraito-Shutdown": shutdownToken, "Content-Length": 0 } },
      (res) => { res.resume(); resolve(res.statusCode === 202); },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.end();
  });
}

async function stopBackend() {
  if (!backend) return;
  const child = backend;
  // Let the backend finish what it is writing (its ASGI shutdown runs), then end it if it hasn't stopped.
  const exited = new Promise((resolve) => child.once("exit", () => resolve(true)));
  if (await askBackendToStop()) {
    const stopped = await Promise.race([exited, new Promise((r) => setTimeout(() => r(false), SHUTDOWN_WAIT_MS))]);
    if (stopped) {
      log("backend stopped");
      return;
    }
  }
  forceStop();
}

function healthy(port) {
  return new Promise((resolve) => {
    const req = http.get({ host: HOST, port, path: tool.healthPath, timeout: 1500 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(port) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (!backend) throw new Error(`The ${tool.name} engine stopped while starting.`);
    if (await healthy(port)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`The ${tool.name} engine did not start within 60 seconds.`);
}

function onBackendLost(code) {
  if (quitting) return;
  const choice = dialog.showMessageBoxSync(mainWindow || undefined, {
    type: "error",
    title: tool.name,
    message: `The ${tool.name} engine stopped unexpectedly.`,
    detail: `${tool.crashMessage}\nExit code: ${code}\nLog folder: ${logDir}`,
    buttons: [`Restart ${tool.name}`, "Close"],
    defaultId: 0,
    cancelId: 1,
  });
  if (choice === 0) {
    app.relaunch();
  }
  quitting = true;
  app.exit(0);
}

function fatal(message) {
  log(`fatal: ${message}`);
  dialog.showErrorBox(`${tool.name} could not start`, `${message}\n\nLog folder: ${logDir}`);
  quitting = true;
  forceStop();
  app.exit(1);
}

// ---- security ---------------------------------------------------------------------------------------------
function isOurOrigin(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" && u.hostname === HOST && Number(u.port) === backendPort;
  } catch {
    return false;
  }
}

function isExternalAllowed(url) {
  return tool.externalLinks.some((prefix) => url === prefix || url.startsWith(prefix));
}

function lockDownSession(ses) {
  // 1. Nothing but our own backend and the local loading page may be requested.
  ses.webRequest.onBeforeRequest((details, callback) => {
    const url = details.url;
    const allowed = isOurOrigin(url) || url === loadingUrl || url.startsWith("devtools:") ||
      url.startsWith("blob:") || url.startsWith("data:");
    if (!allowed) {
      let origin = url;
      try { origin = new URL(url).origin; } catch { /* keep the raw text */ }
      log(`blocked request ${details.method} ${origin}`);
    }
    callback({ cancel: !allowed });
  });
  // 2. A strict Content-Security-Policy on everything the backend serves.
  ses.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...details.responseHeaders };
    if (isOurOrigin(details.url)) {
      headers["Content-Security-Policy"] = [
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
          "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; " +
          "frame-ancestors 'none'",
      ];
    }
    callback({ responseHeaders: headers });
  });
  // 3. No camera, microphone, location, notifications...
  ses.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
}

function lockDownContents(contents) {
  contents.on("will-navigate", (event, url) => {
    if (!isOurOrigin(url) && url !== loadingUrl) event.preventDefault();
  });
  contents.setWindowOpenHandler(({ url }) => {
    // window.open() and target="_blank" links: only the tool's listed https links, in the user's own browser.
    if (isExternalAllowed(url)) shell.openExternal(url);
    else log(`blocked window ${url.slice(0, 120)}`);
    return { action: "deny" };
  });
  contents.on("will-attach-webview", (event) => event.preventDefault());
}

// ---- IPC: two tiny, argument-free requests, accepted only from our own page -------------------------------
function trusted(event) {
  const url = event.senderFrame ? event.senderFrame.url : "";
  return isOurOrigin(url);
}
ipcMain.handle("yoraito:app-info", (event) => {
  if (!trusted(event)) throw new Error("Not allowed.");
  return { name: tool.name, version: app.getVersion(), dataFolder: dataDir };
});
ipcMain.handle("yoraito:open-data-folder", async (event) => {
  if (!trusted(event)) throw new Error("Not allowed.");
  return (await shell.openPath(dataDir)) === ""; // openPath returns "" on success
});

// ---- window -----------------------------------------------------------------------------------------------
function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: tool.name,
    backgroundColor: "#ffffff",
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      devTools: !app.isPackaged,
    },
  });
  win.once("ready-to-show", () => win.show());
  lockDownContents(win.webContents);
  win.on("closed", () => {
    mainWindow = null;
  });
  return win;
}

function buildMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "File",
        submenu: [
          { label: "Open data folder", click: () => shell.openPath(dataDir) },
          { label: "Open log folder", click: () => shell.openPath(logDir) },
          { type: "separator" },
          { role: "quit", label: "Exit" },
        ],
      },
      { label: "View", submenu: [{ role: "reload" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { role: "togglefullscreen" }] },
      { label: "Help", submenu: [{ label: `${tool.name} ${app.getVersion()} - your data stays on this computer`, enabled: false }] },
    ]),
  );
}

async function start() {
  log(`${tool.name} ${app.getVersion()} starting (packaged=${app.isPackaged})`);
  buildMenu();
  mainWindow = createWindow();
  mainWindow.loadFile(loadingPage);
  backendPort = await choosePort();
  lockDownSession(session.defaultSession);
  startBackend(backendPort);
  await waitForBackend(backendPort);
  log("backend healthy");
  await mainWindow.loadURL(`http://${HOST}:${backendPort}/`);
}

app.on("before-quit", (event) => {
  quitting = true;
  if (backend && !stopping) {
    // Quit once the backend has stopped, so it can finish writing first.
    event.preventDefault();
    stopping = true;
    stopBackend().finally(() => app.quit());
  }
});
app.on("window-all-closed", () => app.quit());
process.on("exit", forceStop); // last resort if Electron goes away without before-quit
