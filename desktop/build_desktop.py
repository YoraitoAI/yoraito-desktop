"""Build a Yoraito tool's Windows installer. The same file for every tool; it reads tool.json next to it.

    python desktop/build_desktop.py            (from the tool's repository root, with its Python environment)

Steps:
  1. build the tool's web frontend, if tool.json "build.frontend" names one;
  2. package the Python backend as a one-folder PyInstaller build (desktop/stage/backend/<id>-backend/);
  3. write THIRD-PARTY-NOTICES.txt with packaging/third_party_notices.py, if "build.noticesPackage" is set;
  4. package Electron and the backend into an NSIS installer with electron-builder (config made from tool.json);
  5. write the installer's SHA-256 checksum and short release notes.

Results land in <repository>/release/. Nothing is uploaded or published. Needs Node.js and npm, and a Python with the
tool's dependencies and PyInstaller (see docs/DESKTOP.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parent
STAGE = DESKTOP / "stage"
RELEASE = ROOT / "release"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"


def load_tool() -> dict:
    tool = json.loads((DESKTOP / "tool.json").read_text(encoding="utf-8"))
    for key in ("name", "id", "appId", "version"):
        if not tool.get(key):
            sys.exit(f'tool.json: "{key}" is required')
    if tool["appId"] == "ai.yoraito.example" and tool["id"] != "yoraito-example":
        sys.exit('tool.json: set "appId" to this tool\'s own id (e.g. "ai.yoraito.recon"); every tool needs its own')
    return tool


def run(cmd: list[str], cwd: Path, **kw) -> None:
    print(f"\n> {' '.join(cmd)}   (in {cwd})", flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True, **kw)


def build_frontend(tool: dict) -> None:
    frontend = (tool.get("build") or {}).get("frontend")
    if not frontend:
        print("No frontend to build (tool.json build.frontend is empty).")
        return
    web = ROOT / frontend["dir"]
    for command in frontend.get("commands") or [["npm", "ci"], ["npm", "run", "build"]]:
        command = [NPM if command[0] == "npm" else command[0], *command[1:]]
        run(command, web)


def build_backend(tool: dict) -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing in this Python. See docs/DESKTOP.md (build setup).")
    build = tool.get("build") or {}
    name = f"{tool['id']}-backend"
    out = STAGE / "backend"
    work = STAGE / "_pyinstaller"
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--onedir", "--noconsole", "--noconfirm", "--clean",
        "--distpath", str(out), "--workpath", str(work), "--specpath", str(work),
        # tool.json travels with the backend: desktop_entry.py reads its "backend" settings at start.
        "--add-data", f"{DESKTOP / 'tool.json'}{os.pathsep}.",
        "--icon", str(DESKTOP / "assets" / "icon.ico"),
        # Build and test tools that live in the build environment; the app never imports them.
        "--exclude-module", "pytest", "--exclude-module", "_pytest", "--exclude-module", "setuptools",
        "--exclude-module", "pip",
    ]
    for path in build.get("pythonPaths") or []:
        cmd += ["--paths", str(ROOT / path)]
    for source, destination in build.get("addData") or []:
        cmd += ["--add-data", f"{ROOT / source}{os.pathsep}{destination}"]
    for module in build.get("hiddenImports") or []:
        cmd += ["--hidden-import", module]
    for package in build.get("collectSubmodules") or []:
        cmd += ["--collect-submodules", package]
    cmd.append(str(DESKTOP / "desktop_entry.py"))
    run(cmd, ROOT)
    exe = out / name / (f"{name}.exe" if sys.platform == "win32" else name)
    if not exe.exists():
        sys.exit(f"The backend was not built: {exe} is missing.")


def write_notices(tool: dict) -> Path | None:
    package = (tool.get("build") or {}).get("noticesPackage")
    script = ROOT / "packaging" / "third_party_notices.py"
    if not package:
        print("No third-party notices (tool.json build.noticesPackage is empty).")
        return None
    if not script.exists():
        sys.exit(f"{script} is missing: copy packaging/ from the yoraito-desktop template.")
    out = STAGE / "THIRD-PARTY-NOTICES.txt"
    run([sys.executable, str(script), str(out), "--package", package, "--title", tool["name"], "--electron"], ROOT)
    return out


def builder_config(tool: dict, notices: Path | None) -> Path:
    """electron-builder's settings, made from tool.json, so there is no second place to keep in step."""
    backend = f"{tool['id']}-backend"
    resources = [{"from": f"stage/backend/{backend}", "to": f"backend/{backend}"}]
    if notices:
        resources.append({"from": "stage/THIRD-PARTY-NOTICES.txt", "to": "THIRD-PARTY-NOTICES.txt"})
    config = {
        "appId": tool["appId"],
        "productName": tool["name"],
        "directories": {"output": str(RELEASE), "buildResources": "assets"},
        "files": ["main.js", "preload.js", "loading.html", "tool.json", "assets/**", "package.json"],
        "extraResources": resources,
        "extraMetadata": {"name": tool["id"], "version": tool["version"], "description": tool.get("description", "")},
        "asar": True,
        "win": {"target": [{"target": "nsis", "arch": ["x64"]}], "icon": "assets/icon.ico"},
        "nsis": {
            "oneClick": False,
            "perMachine": False,  # installs for the current user: no administrator rights needed
            "allowToChangeInstallationDirectory": True,
            "artifactName": f"{tool['id']}-setup-${{version}}.${{ext}}",
            "deleteAppDataOnUninstall": False,  # the user's data in ~/.yoraito stays
        },
    }
    path = STAGE / "electron-builder.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def build_installer(tool: dict, notices: Path | None) -> Path:
    if not (DESKTOP / "node_modules" / "electron-builder").exists():
        run([NPM, "ci"], DESKTOP)
    shutil.rmtree(RELEASE, ignore_errors=True)
    config = builder_config(tool, notices)
    run([NPX, "electron-builder", "--config", str(config), "--win", "nsis", "--x64", "--publish", "never"], DESKTOP)
    installer = RELEASE / f"{tool['id']}-setup-{tool['version']}.exe"
    if not installer.exists():
        sys.exit(f"The installer was not created: {installer} is missing.")
    return installer


def write_checksum(installer: Path) -> str:
    digest = hashlib.sha256()
    with installer.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    value = digest.hexdigest()
    (RELEASE / f"{installer.name}.sha256").write_text(f"{value} *{installer.name}\n", encoding="ascii")
    return value


def write_release_notes(tool: dict, installer: Path, checksum: str) -> None:
    size = installer.stat().st_size
    (RELEASE / "RELEASE_NOTES.md").write_text(
        f"""# {tool['name']} {tool['version']} for Windows

{tool.get('description', '')}

* Installer: `{installer.name}` ({size:,} bytes, {size / (1024 * 1024):.0f} MB), Windows 10/11, 64-bit
* SHA-256: `{checksum}`. Check it in PowerShell: `Get-FileHash .\\{installer.name} -Algorithm SHA256`
* Installs for the current user; no administrator rights needed.
* Data: `%USERPROFILE%\\.yoraito\\{tool['id']}\\` (or `%YORAITO_HOME%\\{tool['id']}\\`). Uninstalling keeps it.
* If the installer isn't code-signed yet, Windows SmartScreen shows "Windows protected your PC": click
  **More info**, then **Run anyway**.
""",
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Yoraito tool's Windows installer from desktop/tool.json.")
    ap.add_argument("--skip-frontend", action="store_true", help="reuse the already built web frontend")
    ap.add_argument("--skip-backend", action="store_true", help="reuse the already built backend (desktop/stage)")
    args = ap.parse_args()
    tool = load_tool()
    if not (DESKTOP / "assets" / "icon.ico").exists():
        sys.exit("desktop/assets/icon.ico is missing: run desktop/make_icon.py, or add the tool's icon.")
    STAGE.mkdir(exist_ok=True)
    if not args.skip_frontend:
        build_frontend(tool)
    if not args.skip_backend:
        build_backend(tool)
    notices = write_notices(tool)
    installer = build_installer(tool, notices)
    checksum = write_checksum(installer)
    write_release_notes(tool, installer, checksum)
    print("\nInstaller:", installer)
    print("Size     :", f"{installer.stat().st_size:,} bytes")
    print("SHA-256  :", checksum)


if __name__ == "__main__":
    main()
