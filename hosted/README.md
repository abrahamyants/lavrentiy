# Lavrentiy hosted demo

A single-page browser demo of Layer-4 reconstruction. Designed for cold-outreach
to foundations/SLP clinics where asking them to download a `.exe` is a non-starter
(SmartScreen warning + install friction + Windows-only).

## What this is, and what it isn't

This is **not** the desktop Lavrentiy engine. It's a minimal hosted variant that:

- Reuses `wim/api/prompt_builder.py` — same L4 system prompt the desktop uses,
  so reconstruction quality matches.
- Strips everything else: no profile, no hotkeys, no tray, no paste, no audio
  DSP, no local Whisper. Cloud Whisper for ASR, Anthropic Sonnet with extended
  thinking for reconstruction.
- Layer pinned at 4. Empty profile. First-time-ever-user simulation.

## Local dev

```bash
cd hosted
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
pip install -r requirements.txt
uvicorn app:app --reload --port 8080
# open http://127.0.0.1:8080
```

The server imports `prompt_builder` from `../wim/api/`, so it must be run from
the repo (not copied elsewhere).

## Deploy

See `deploy.sh` — Cloud Run with secrets-bound API keys. Run from repo root.
