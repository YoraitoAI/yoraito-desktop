# Packaging a Yoraito tool as a desktop app (Electron)

The desktop app is the tool's own web app in a window. Electron starts the tool's Python backend on 127.0.0.1, waits for it to answer, and shows the page it serves. The interface is the same as the web version.

## What's in `desktop/`

| File | What it does | Edit per tool? |
|---|---|---|
| `tool.json` | Everything that differs between tools ([PLACEHOLDERS.md](../PLACEHOLDERS.md)) | yes |
| `main.js` | Electron main process: one instance per tool, starts and stops the backend, locks down the window | no |
| `preload.js` | The two calls the page can make: app info, open the data folder | no |
| `desktop_entry.py` | The backend program PyInstaller packages: data folder, legacy copy, blocked routes, shutdown, runs the ASGI app | no |
| `build_desktop.py` | Builds the frontend, backend, notices and installer | no |
| `loading.html` | Shown while the backend starts | no |
| `package.json`, `package-lock.json` | Electron and electron-builder, pinned | no |
| `make_icon.py`, `assets/` | The placeholder icon; replace `assets/icon.ico` with the tool's | the icon only |

## The backend contract

`desktop_entry.py` imports `backend.app` from tool.json and serves it with uvicorn on `127.0.0.1:$YORAITO_PORT`. For that to work:

1. **`backend.app` is an ASGI app,** as `module:attribute`. A FastAPI app works, and so does one already wrapped by yoraito-core's `LocalGuard`. If the attribute is a function that builds the app, set `"factory": true`.
2. **The app answers `healthPath` with HTTP 200** once it can serve the page. Electron waits up to 60 seconds for it.
3. **Background work starts in the app's ASGI lifespan,** not in a separate `main()`: this program only serves the app. The lifespan's shutdown runs when the desktop app closes. Electron asks for it with `POST /__desktop/shutdown`, which carries a token only Electron knows, and waits up to 5 seconds before ending the process.
4. **The app serves its interface at `/`.**

The backend also receives:

| Variable | Value |
|---|---|
| `YORAITO_DESKTOP` | `1` |
| `YORAITO_PORT` | The port to serve on |
| `YORAITO_DATA_DIR` | The tool's data folder |
| `YORAITO_PARENT_PID` | Electron's process id; the backend exits if that process is gone |
| `YORAITO_SHUTDOWN_TOKEN` | The shutdown token |

A tool that reads its port from its own setting maps it in `backend.env`, where `{port}` is the port and `{data}` the data folder: for example `{"YORAITO_SYNC_PORT": "{port}"}`.

## Ports

With `"port": 0` the backend gets a free port at every start. That suits a tool whose address only the window uses.

A tool whose address is written somewhere else needs a fixed port. Examples are a workbook's Power Query URL, an AI client's MCP settings, and an OAuth redirect URI registered with Intuit, Xero or Google. For those, set `"port"` to that number. If another program holds the port, the app says so and doesn't start.

## Privacy and security

The window may only talk to its own backend:

- **Requests:** every request to anything else is cancelled, and every response from the backend gets a strict Content-Security-Policy.
- **Navigation:** limited to the backend and the loading page.
- **Links:** `window.open` and `target="_blank"` links open in the user's browser only if they match an https prefix in `externalLinks`.
- **Permissions:** camera, microphone, location and notifications are all denied.
- **IPC:** the two calls are accepted only from the backend's page.
- **The renderer** runs sandboxed, with context isolation and no Node.

A tool that must not send data out lists its routes in `backend.blockedRoutes` and the variables that would enable them in `backend.scrubEnv`.

## Data

`%USERPROFILE%\.yoraito\<id>` (or `%YORAITO_HOME%\<id>`), the same layout as yoraito-core's `paths` module:

| Item | Location |
|---|---|
| The tool's own data | wherever the app writes it, normally under this folder (`{data}` in `backend.env`) |
| Logs | `logs\desktop.log` (the window), `logs\backend.log` and `logs\backend-output.log` (the backend) |
| Electron's profile (and the single-instance lock) | `electron\` |

Each tool has its own folder, so two Yoraito desktop apps can run at the same time. Uninstalling keeps the folder.

**Moving from an earlier folder:** list it in `backend.legacyDataDirs`. On the first start, if the new folder holds no data yet, the contents of the first listed folder that exists are copied in. The original is left as it was; a `.migrated-from` file records the copy.

## Build

Needs Node.js 20+ and the tool's Python environment with PyInstaller 6+:

```
pip install "pyinstaller>=6"
python desktop/build_desktop.py
```

The first build runs `npm ci` in `desktop/`, which downloads Electron. The results are in `release/`, git-ignored:
- `<id>-setup-<version>.exe`;
- its `.sha256` file;
- `RELEASE_NOTES.md`.

electron-builder's settings are written to `desktop/stage/electron-builder.json` from tool.json at every build, so there is no second config file to keep in step.

**Running without installing:** build the backend once (`build_desktop.py` does), then `cd desktop && npm start`.

The installer isn't code-signed yet. Signing goes into `build_desktop.py` once Yoraito has a signing route (see yoraito-sync's RELEASE-PLAN, section 3).

## Adopting the template

**yoraito-model-diff:** its current desktop folder becomes:
- **`tool.json`:** the values in the model-diff column of PLACEHOLDERS.md;
- **`legacyDataDirs`:** both of its earlier folders;
- **the "Open in Google Sheets" button:** it now calls `window.open("https://sheets.new/")` directly. The shell no longer turns a blank window into a Sheets tab.

**yoraito-sync:** stays on Inno Setup for now:
- it runs in the background with a tray icon after its window closes;
- it needs its fixed port, 8765;
- its window is native, not a web page.

It can use `packaging/installer.iss.template` (keeping its existing AppId) and `packaging/third_party_notices.py`.
