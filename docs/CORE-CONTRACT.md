# The packaging contract a desktop tool expects

This repository is a template: Electron for a web app in its own window, Inno Setup for a single exe
with a tray icon. It contains no Python, and it should not gain any. The tool provides the backend
and the behaviour.

## What the tool provides

- An ASGI backend with `GET /health`.
- A data folder from `yoraito_core.paths.app_dir("<tool>")`, default `~/.yoraito/<tool>` on macOS and
  Linux, `%USERPROFILE%\.yoraito\<tool>` on Windows.
- A per-install key from `yoraito_core.installkey`. Non-browser clients send `X-Yoraito-Key`; the
  browser pages the tool serves use the session cookie.
- A local API guarded by `yoraito_core.localapi`: Host `127.0.0.1` or `localhost`, Origin allowlist,
  no CORS.

## What the template provides

- The window, the tray icon, the installer and the health check.
- No product logic and no copy of the guard or the key handling.
- Uninstall keeps the data folder. Say so in the tool's install guide.

## Why there is no core code here

The template is copied into every tool. A second copy of paths, key handling or the local API guard
would drift from core. The template states the contract; the tool uses core.

## Checklist

- [ ] The backend has `GET /health`.
- [ ] Data is under `paths.app_dir("<tool>")`.
- [ ] The install key comes from `installkey`.
- [ ] The local API uses `localapi`.
- [ ] The installer keeps the data folder on uninstall and says so.
