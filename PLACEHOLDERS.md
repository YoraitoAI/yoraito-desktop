# What to fill in

## Electron tools: `desktop/tool.json`

The only file a tool edits; `main.js`, `desktop_entry.py` and `build_desktop.py` read it. The values shown are the example app's.

| Field | Meaning | Example (model-diff) |
|---|---|---|
| `name` | Display name: window title, Start menu, dialogs | `"Yoraito Model Diff"` |
| `id` | Lowercase and hyphenated. Names the data folder (`~/.yoraito/<id>`), the backend exe and the installer | `"yoraito-model-diff"` |
| `appId` | electron-builder's app id, unique per tool. Never change it after the first release | `"ai.yoraito.model-diff"` |
| `version` | The installer's version | `"1.0.0"` |
| `description` | One line for the release notes | `"Compare two versions of an Excel model."` |
| `port` | `0`: a free port at each start. A number: always that port, for tools whose port is written elsewhere (workbooks, AI client settings, registered sign-in addresses) | `0` |
| `healthPath` | The route that answers HTTP 200 once the backend is ready | `"/api/health"` |
| `externalLinks` | https URL prefixes the page may open in the user's browser (with `window.open` or a `target="_blank"` link). Everything else is blocked | `["https://sheets.new/"]` |
| `crashMessage` | Shown when the backend stops unexpectedly | `"Your saved comparisons are safe."` |
| `backend.app` | The ASGI app, as `module:attribute` | `"yoraito_model_diff.web.app:app"` |
| `backend.factory` | `true` when the attribute is a function that returns the app | `false` |
| `backend.blockedRoutes` | Path prefixes that answer 404 in the desktop app | `["/api/ai-summary", "/api/llm-status", "/api/diff-sheets"]` |
| `backend.scrubEnv` | Environment variables removed before the app loads | `["YORAITO_AI_API_KEY", "OPENAI_API_KEY"]` |
| `backend.env` | Environment variables set before the app loads; `{data}` is the tool's data folder and `{port}` its port | `{"YORAITO_REVIEW_DB": "{data}/reviews.db"}` |
| `backend.legacyDataDirs` | Folders whose contents are copied into the data folder the first time, if it is empty. Copied, never moved. `%VAR%` and `~` are expanded | `["%LOCALAPPDATA%\\Yoraito", "%LOCALAPPDATA%\\yoraito-model-diff"]` |
| `build.pythonPaths` | Folders added to PyInstaller's search path, relative to the repository root | `["src"]` |
| `build.addData` | `[source, destination]` pairs bundled with the backend, e.g. the built web UI | `[["src/yoraito_model_diff/web/static", "yoraito_model_diff/web/static"]]` |
| `build.hiddenImports` | Modules PyInstaller can't find on its own | `["yoraito_model_diff.web.app"]` |
| `build.collectSubmodules` | Packages to include whole | `["uvicorn"]` |
| `build.frontend` | `null`, or `{"dir": "webui", "commands": [["npm", "ci"], ["npm", "run", "build"]]}` | as shown |
| `build.noticesPackage` | The tool's Python distribution, for THIRD-PARTY-NOTICES.txt | `"yoraito-model-diff"` |

## Inno Setup tools: `packaging/installer.iss`

The four `#define` lines at the top of `installer.iss.template`:

| Define | Meaning | Example (yoraito-sync) |
|---|---|---|
| `AppId` | A new GUID for this tool, written `{{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`. Never reuse another tool's; never change it after the first release | yoraito-sync keeps its existing id |
| `AppName` | Display name | `Yoraito Sync` |
| `ToolId` | Lowercase and hyphenated; the exe is `dist\<ToolId>.exe` | `yoraito-sync` |
| `StartupTask` | `yes` offers "Start when I sign in to Windows" | `yes` |

`iscc` stops with an error while `AppId`, `AppName` or `ToolId` still hold their placeholders, or if `AppId` is Yoraito Sync's.
