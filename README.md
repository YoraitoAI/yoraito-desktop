# yoraito-desktop

The shared Windows packaging for Yoraito tools. There are two ways to ship a tool, depending on what it is:

| Kind of tool | What to copy | Installer |
|---|---|---|
| A web app in its own window (model-diff, recon) | `desktop/` and `packaging/third_party_notices.py` | NSIS, made by electron-builder from `desktop/tool.json` |
| One exe with its own window or tray icon, no Electron (yoraito-sync) | `packaging/` | Inno Setup, from `packaging/installer.iss.template` |

## A web app in its own window (Electron)

The code in `desktop/` is the same for every tool. What differs is in one file, `desktop/tool.json`: the tool's name, id, port, health route, the links it may open, and how to package its backend.

1. Copy `desktop/` into the tool's repository as `desktop/`, and `packaging/third_party_notices.py` as `packaging/third_party_notices.py`.
2. Edit `desktop/tool.json` (every field is described in [PLACEHOLDERS.md](PLACEHOLDERS.md)). Replace `desktop/assets/icon.ico` with the tool's icon, or keep the placeholder.
3. In the tool's Python environment, with PyInstaller installed: `python desktop/build_desktop.py`
4. The installer, its checksum and short release notes are in `release/`.

The backend has to follow a short contract: an ASGI app, a health route, background work in its lifespan. See [docs/DESKTOP.md](docs/DESKTOP.md).

To try the template as it is, `example/hello_app.py` is a minimal backend, and `desktop/tool.json` points at it:

```
pip install fastapi uvicorn "pyinstaller>=6"
python desktop/build_desktop.py
```

## One exe without Electron (Inno Setup)

1. Copy `packaging/installer.iss.template` to `packaging/installer.iss` in the tool's repository and fill in the four `#define` lines at the top. `AppId` must be a new GUID; the script refuses to compile with the placeholder or with Yoraito Sync's id.
2. Build the exe to `dist\<ToolId>.exe`, and the notices with `python packaging/third_party_notices.py dist/THIRD-PARTY-NOTICES.txt --package <python package>`.
3. `iscc /DAppVersion=<version> packaging\installer.iss` writes `dist\<ToolId>-setup.exe`.

## Getting later fixes

Tools copy these files, so a fix here doesn't reach them by itself. Because everything tool-specific is in `desktop/tool.json` (or the `#define` block of `installer.iss`), updating a tool means copying the other files again; nothing in them needs editing. A Copier template or versioned packages would automate that later.

## Data

Every tool keeps its data in its own folder, `%USERPROFILE%\.yoraito\<id>` (or `%YORAITO_HOME%\<id>`): the layout yoraito-core's `paths` module uses. Electron's own profile and the logs are in that folder too, so two Yoraito tools can run side by side. Uninstalling keeps the folder.

## License

MIT, see [LICENSE](LICENSE).

## Yoraito Core

No core code belongs in this template. Document the packaging contract against `yoraito_core.paths` and `yoraito_core.installkey` so every tool uses the same data folder and per-install key. See `yoraito-core/docs/ADOPTION.md` and `docs/GENERICITY.md`.
