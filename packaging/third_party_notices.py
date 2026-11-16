"""Write THIRD-PARTY-NOTICES.txt for a Yoraito tool's Windows build: every package the program bundles, its
licence and its licence text, plus the pieces PyInstaller (and Electron) bundle that aren't Python packages.

    python packaging/third_party_notices.py dist/THIRD-PARTY-NOTICES.txt --package yoraito-sync --extra gui
    python packaging/third_party_notices.py desktop/stage/THIRD-PARTY-NOTICES.txt --package yoraito-recon --electron

The packages are the named distribution's runtime dependencies (with any --extra), followed through their own
requirements, as installed in this environment, so the versions are the ones the tool's lock file pins.
Yoraito's own packages (yoraito-*) are left out. desktop/build_desktop.py runs this for Electron builds.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import sys
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

LICENCE_FILE_WORDS = ("license", "licence", "copying", "notice", "authors")

# Bundled by PyInstaller without being a dependency in uv.lock.
BUNDLED = [
    ("Python", "the runtime the exe is built with", "PSF-2.0 (Python Software Foundation License)",
     "https://docs.python.org/3/license.html"),
    ("Tcl/Tk", "the window toolkit, through Python's tkinter", "TCL (BSD-style Tcl/Tk license)",
     "https://www.tcl.tk/software/tcltk/license.html"),
    ("PyInstaller bootloader", "starts the bundled program", "GPL-2.0-or-later WITH Bootloader-exception",
     "https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt"),
]


@dataclass
class Component:
    name: str
    version: str
    licence: str
    homepage: str
    texts: list[tuple[str, str]] = field(default_factory=list)


def licence_of(meta) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c != "OSI Approved"]
    if classifiers:
        return ", ".join(dict.fromkeys(classifiers))
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 80:
        return text
    return "see the licence text below" if text else "not stated in the package metadata"


def homepage_of(meta) -> str:
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "source code", "repository", "github"):
            return url.strip()
    return (meta.get("Home-page") or "").strip()


def licence_texts(dist) -> list[tuple[str, str]]:
    texts = []
    for path in dist.files or []:
        name = path.name.lower()
        in_metadata = any(part.endswith((".dist-info", ".egg-info")) for part in path.parts)
        if in_metadata and any(word in name for word in LICENCE_FILE_WORDS):
            try:
                texts.append((path.name, dist.locate_file(path).read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                continue
    if not texts:
        text = (dist.metadata.get("License") or "").strip()
        if "\n" in text or len(text) > 80:
            texts.append(("License (from the package metadata)", text))
    return texts


def components(root: str, extras: tuple[str, ...] = ()) -> list[Component]:
    """Every distribution the root needs at run time, by canonical name, followed through requirements."""
    found: dict[str, Component] = {}
    stack = [(root, set(extras))]
    visited: set[tuple[str, frozenset[str]]] = set()
    while stack:
        name, wanted = stack.pop()
        key = canonicalize_name(name)
        if (key, frozenset(wanted)) in visited:
            continue
        visited.add((key, frozenset(wanted)))
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue  # an optional requirement that isn't installed, so it isn't bundled either
        if not key.startswith("yoraito") and key not in found:
            meta = dist.metadata
            found[key] = Component(meta["Name"], dist.version, licence_of(meta), homepage_of(meta), licence_texts(dist))
        for line in dist.requires or []:
            req = Requirement(line)
            if req.marker and not any(req.marker.evaluate({"extra": e}) for e in (wanted | {""})):
                continue
            stack.append((req.name, set(req.extras)))
    return sorted(found.values(), key=lambda c: c.name.lower())


ELECTRON = ("Electron", "the desktop window (Chromium and Node.js)",
            ("MIT; Chromium's own licences are in LICENSES.chromium.html next to the program"),
            "https://github.com/electron/electron/blob/main/LICENSE")


def render(items: list[Component], title: str, version: str, electron: bool = False) -> str:
    lines = [f"Third-party software in {title} {version}", "=" * 60, "",
             f"{title} includes the open-source software listed here, each under its own licence. The licence",
             "texts follow the list."]
    if any(c.name.lower() == "pystray" for c in items):
        lines += ["pystray is used unmodified under the LGPL; its source is at https://github.com/moses-palmer/pystray."]
    lines += ["", "Bundled with the program:"]
    bundled = [*BUNDLED, ELECTRON] if electron else BUNDLED
    lines += [f"  {name}: {what}. Licence: {licence}. {url}" for name, what, licence, url in bundled]
    lines += ["", "Python packages:"]
    width = max(len(c.name) for c in items) if items else 10
    lines += [f"  {c.name.ljust(width)}  {c.version.ljust(12)}  {c.licence}" for c in items]
    for c in items:
        lines += ["", "-" * 60, f"{c.name} {c.version}", f"Licence: {c.licence}"]
        if c.homepage:
            lines.append(f"Project: {c.homepage}")
        for filename, text in c.texts:
            lines += ["", f"[{filename}]", text]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description="Write THIRD-PARTY-NOTICES.txt for a Yoraito tool's build.")
    ap.add_argument("out", type=Path, help="the file to write")
    ap.add_argument("--package", required=True, help="the tool's Python distribution, e.g. yoraito-sync")
    ap.add_argument("--extra", action="append", default=[], help="an extra whose requirements are bundled too")
    ap.add_argument("--title", help="the product name in the heading (default: from the package metadata)")
    ap.add_argument("--electron", action="store_true", help="the program also bundles Electron")
    args = ap.parse_args(argv[1:])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    items = components(args.package, tuple(args.extra))
    title = args.title or md.metadata(args.package)["Name"]
    args.out.write_text(render(items, title, md.version(args.package), args.electron), encoding="utf-8")
    print(f"{args.out}: {len(items)} packages")


if __name__ == "__main__":
    main(sys.argv)
