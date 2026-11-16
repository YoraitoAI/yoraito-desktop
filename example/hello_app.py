"""The smallest backend the desktop template can run, to try it end to end:

    pip install fastapi uvicorn pyinstaller
    python desktop/make_icon.py
    python desktop/build_desktop.py

A real tool replaces desktop/tool.json "backend.app" with its own app and deletes this folder.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Yoraito Example</title></head>"
            "<body style='font-family: Segoe UI, sans-serif; margin: 40px'><h1>Yoraito Example</h1>"
            "<p>The desktop shell started this backend and shows its page.</p></body></html>")
