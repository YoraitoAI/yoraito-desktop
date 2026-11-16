"""Backend entry point for a Yoraito desktop app: the program Electron starts. The same file for every tool;
what differs is in tool.json "backend" (bundled next to this program by build_desktop.py).

It runs the tool's ASGI app (FastAPI, or one wrapped by yoraito-core's LocalGuard) quietly for the desktop shell:

* no console window and no browser: Electron shows the interface;
* it listens on 127.0.0.1 only, on the port Electron passes in ``YORAITO_PORT``;
* data lives in the tool's own folder, ``YORAITO_DATA_DIR`` from Electron: ``<YORAITO_HOME or ~/.yoraito>/<id>``;
* folders listed in ``legacyDataDirs`` are COPIED in the first time, never moved or overwritten;
* path prefixes in ``blockedRoutes`` answer 404, and variables in ``scrubEnv`` are removed before the app loads;
* ``env`` sets variables before the app loads, with ``{data}`` (the data folder) and ``{port}`` filled in;
* Electron stops it with POST /__desktop/shutdown (a token only Electron knows), so the app's own shutdown runs;
* if Electron disappears without stopping it (a crash), this program notices and exits.

The backend contract: ``backend.app`` names ``module:attribute``, an ASGI app (or, with ``"factory": true``, a
function returning one). Work the app runs in the background starts in its ASGI lifespan, because this program
only serves the app. It must answer the health route (tool.json ``healthPath``) with HTTP 200.
"""
from __future__ import annotations

import hmac
import importlib
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path

# Running without a console (PyInstaller --noconsole): uvicorn's logging expects real streams.
# They stay open for the life of the program.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MIGRATION_MARKER = ".migrated-from"


def load_tool() -> dict:
    return json.loads((HERE / "tool.json").read_text(encoding="utf-8"))


def data_dir(tool: dict) -> Path:
    """Where this tool keeps its data: the folder Electron passes in, else yoraito-core's layout."""
    given = os.environ.get("YORAITO_DATA_DIR")
    path = Path(given) if given else Path(os.environ.get("YORAITO_HOME") or Path.home() / ".yoraito") / tool["id"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_legacy_data(new_dir: Path, legacy_dirs: list[str]) -> str:
    """Copy the first existing legacy folder into ``new_dir`` once. Returns what happened.

    Copy, never move: the old folder is left exactly as it was. Nothing in ``new_dir`` is overwritten. The shell's
    own folders (``electron``, ``logs``) don't count as data. A marker file records that the copy was made.
    """
    if (new_dir / MIGRATION_MARKER).exists():
        return "copied earlier"
    if any(p.name not in ("electron", "logs") for p in new_dir.iterdir()):
        return "kept existing data"
    for raw in legacy_dirs:
        legacy = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not legacy.is_dir() or legacy.resolve() == new_dir.resolve():
            continue
        made: list[Path] = []
        try:
            for item in legacy.iterdir():
                if item.name in ("electron", "logs"):
                    continue  # another shell's profile and logs are not data
                target = new_dir / item.name
                if target.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
                made.append(target)
            (new_dir / MIGRATION_MARKER).write_text(str(legacy), encoding="utf-8")
        except Exception:
            # Leave nothing half-copied: the next start tries again from the untouched original.
            for path in made:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            raise
        return f"copied {legacy}"
    return "no earlier data"


def _process_is_running(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False  # no such process
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _exit_when_parent_dies(parent_pid: int) -> None:
    while True:
        time.sleep(2)
        if not _process_is_running(parent_pid):
            os._exit(0)


class DesktopApp:
    """An ASGI wrapper: the shutdown route Electron calls, and 404 for the tool's blocked routes.

    A wrapper rather than FastAPI middleware, so it works for any ASGI app, including one already wrapped
    by yoraito-core's LocalGuard.
    """

    def __init__(self, app, blocked: tuple[str, ...], token: str) -> None:
        self.app = app
        self.blocked = blocked
        self.token = token.encode()
        self.server = None  # set once the uvicorn server exists

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/__desktop/shutdown":
                return await self._shutdown(scope, send)
            if self.blocked and path.startswith(self.blocked):
                return await self._answer(send, 404, {"detail": "Not available in the desktop app."})
        return await self.app(scope, receive, send)

    async def _shutdown(self, scope, send):
        given = dict(scope.get("headers") or []).get(b"x-yoraito-shutdown", b"")
        if scope.get("method") != "POST" or not self.token or not hmac.compare_digest(given, self.token):
            return await self._answer(send, 404, {"detail": "Not Found"})
        if self.server is not None:
            self.server.should_exit = True  # uvicorn stops accepting, then runs the app's lifespan shutdown
        return await self._answer(send, 202, {"stopping": True})

    @staticmethod
    async def _answer(send, status: int, body: dict):
        payload = json.dumps(body).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
        await send({"type": "http.response.body", "body": payload})


def configure(tool: dict, port: str) -> Path:
    backend = tool.get("backend") or {}
    for name in backend.get("scrubEnv") or []:
        os.environ.pop(name, None)
    base = data_dir(tool)
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        outcome = copy_legacy_data(base, backend.get("legacyDataDirs") or [])
    except Exception as exc:  # noqa: BLE001  never stop the app over this: it starts without the old data
        outcome = f"could not copy earlier data ({exc.__class__.__name__}); the original was not touched"
    for name, value in (backend.get("env") or {}).items():
        os.environ[name] = str(value).replace("{data}", str(base)).replace("{port}", port)
    logging.basicConfig(filename=logs / "backend.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("yoraito.desktop").info("startup data=%s legacy=%s", base, outcome)
    return base


def load_app(spec: str, factory: bool):
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise SystemExit(f'tool.json backend.app must look like "package.module:app", not {spec!r}')
    target = getattr(importlib.import_module(module_name), attribute)
    return target() if factory else target


def main() -> None:
    port = os.environ.get("YORAITO_PORT", "")
    if not port.isdigit():
        print("YORAITO_PORT must be set by the desktop shell.", file=sys.stderr)
        sys.exit(2)
    tool = load_tool()
    configure(tool, port)

    parent = os.environ.get("YORAITO_PARENT_PID", "")
    if parent.isdigit():
        threading.Thread(target=_exit_when_parent_dies, args=(int(parent),), daemon=True).start()

    import uvicorn

    backend = tool.get("backend") or {}
    app = DesktopApp(load_app(backend["app"], bool(backend.get("factory"))),
                     tuple(backend.get("blockedRoutes") or ()), os.environ.get("YORAITO_SHUTDOWN_TOKEN", ""))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(port), log_config=None, access_log=False))
    app.server = server
    server.run()


if __name__ == "__main__":
    main()
