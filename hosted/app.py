"""Lavrentiy hosted demo — single-page browser demo for foundation/SLP outreach.

NOT the desktop engine. Stripped-down hosted variant:
  - GET  /             -> index.html
  - POST /transcribe   -> {raw, clean, tone, layer}  (multipart audio upload)
  - GET  /healthz      -> readiness probe

Reuses wim/api/prompt_builder.py — same L4 prompt the desktop engine uses,
so the reconstruction output here is identical to local Lav.

Layer pinned at 4 (the clinical reconstruction showcase). Empty profile.
No ASR seed text — Whisper alone, raw. Same as a first-time-ever user.
"""

import io
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "wim" / "api"))

import anthropic
import openai
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import prompt_builder

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not OPENAI_API_KEY or not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY and ANTHROPIC_API_KEY must be set. "
        "On Cloud Run, bind via --set-secrets."
    )

openai_client = openai.OpenAI(api_key=OPENAI_API_KEY, timeout=30, max_retries=2)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60, max_retries=2)

SONNET_THINK_MODEL = "claude-sonnet-4-6"
SONNET_THINK_BUDGET = 8000
SONNET_THINK_MAX_TOKENS = 16000

VALID_TONES = set(prompt_builder.TONE_RULES.keys())

app = FastAPI(title="Lavrentiy Demo", docs_url=None, redoc_url=None)
HERE = Path(__file__).resolve().parent


@app.get("/")
async def index():
    return FileResponse(HERE / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def _suffix_from_content_type(ct: str | None) -> str:
    """MediaRecorder ships webm on Chrome, mp4 on Safari, ogg on Firefox.
    OpenAI's Whisper endpoint content-sniffs from the BytesIO.name suffix."""
    if not ct:
        return ".webm"
    ct = ct.lower()
    if "mp4" in ct or "m4a" in ct:
        return ".mp4"
    if "ogg" in ct:
        return ".ogg"
    if "wav" in ct:
        return ".wav"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    return ".webm"


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    tone: str = Form("casual"),
):
    if tone not in VALID_TONES:
        tone = "casual"

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="audio over 25MB cap")

    suffix = _suffix_from_content_type(audio.content_type)
    buf = io.BytesIO(audio_bytes)
    buf.name = f"clip{suffix}"

    t0 = time.time()
    asr = openai_client.audio.transcriptions.create(
        model="whisper-1",
        file=buf,
    )
    raw_text = (asr.text or "").strip()
    t_asr_ms = int((time.time() - t0) * 1000)

    if not raw_text:
        return {
            "raw": "",
            "clean": "",
            "tone": tone,
            "layer": 4,
            "asr_ms": t_asr_ms,
            "recon_ms": 0,
        }

    system_prompt = prompt_builder.build_prompt(
        raw_text,
        tone=tone,
        layer=4,
        profile={},
        situation="default",
    )

    t1 = time.time()
    msg = anthropic_client.messages.create(
        model=SONNET_THINK_MODEL,
        max_tokens=SONNET_THINK_MAX_TOKENS,
        thinking={"type": "enabled", "budget_tokens": SONNET_THINK_BUDGET},
        system=system_prompt,
        messages=[{"role": "user", "content": raw_text}],
    )
    text_blocks = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    clean_text = "\n".join(text_blocks).strip()
    t_recon_ms = int((time.time() - t1) * 1000)

    return {
        "raw": raw_text,
        "clean": clean_text,
        "tone": tone,
        "layer": 4,
        "asr_ms": t_asr_ms,
        "recon_ms": t_recon_ms,
    }
