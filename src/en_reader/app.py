"""FastAPI skeleton for the en-reader dev server.

Serves the demo fixture built by `scripts/build_demo.py` plus the static
`index.html` stub. The `POST /api/translate` endpoint (M4.1) wraps the
Gemini-backed :func:`en_reader.translate.translate_one`.
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from en_reader.translate import TranslateError, translate_one

load_dotenv()

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="en-reader")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class TranslateRequest(BaseModel):
    unit_text: str = Field(min_length=1, max_length=100)
    sentence: str = Field(min_length=1, max_length=2000)


class TranslateResponse(BaseModel):
    ru: str


@app.get("/")
def root() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/demo")
def api_demo() -> dict:
    demo_path = _STATIC_DIR / "demo.json"
    if not demo_path.exists():
        raise HTTPException(
            status_code=404,
            detail="demo.json not found — run `python scripts/build_demo.py <path>` first",
        )
    with demo_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    try:
        ru = translate_one(req.unit_text, req.sentence)
    except TranslateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return TranslateResponse(ru=ru)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for SPA deep links; let /api/* and /static/* 404 normally."""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    return FileResponse(_STATIC_DIR / "index.html")
