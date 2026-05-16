"""
What I Meant — Reconstruction API
Standalone voice-to-intent reconstruction engine.
Extracted from Лаврентий (lavrentiy.py) for use as a GCP Cloud Function
or any HTTP endpoint.

Takes raw messy text + tone + profile → returns clean text + confidence score (γ).

Usage:
    from reconstruct import reconstruct_intent
    result = reconstruct_intent("so um like the thing is we need to uh get the report", tone="professional")
    # result = {"clean": "We need to get the report.", "confidence": 0.92, "ms": 340}

As Cloud Function:
    Deploy main.py which imports this module and exposes the HTTP handler.
"""

import os
import re
import time

import openai

from prompt_builder import build_prompt, TONE_TEMP, TONE_RULES, SITUATION_SEVERITY

# ─── Config ───
MODEL = os.environ.get("WIM_MODEL", "gpt-4o")
MODEL_L4 = os.environ.get("WIM_MODEL_L4", "gpt-4o")
API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Try reading from api_key.txt (same dir as this file, or parent)
if not API_KEY:
    for p in [
        os.path.join(os.path.dirname(__file__), "api_key.txt"),
        os.path.join(os.path.dirname(__file__), "..", "..", "api_key.txt"),
    ]:
        if os.path.exists(p):
            API_KEY = open(p).read().strip()
            break

client = openai.OpenAI(api_key=API_KEY) if API_KEY else None

# ─── Bilingual filler set ───
_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}


def strip_disfluencies(text):
    """Remove obvious disfluency artifacts from transcription (zero API cost)."""
    if not text or not text.strip():
        return text
    cleaned = re.sub(r'(\b\w+)-\s+(?:\1-\s+)*', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(\w+)(?:\s+\1)+\b', r'\1', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', r'\1', cleaned, flags=re.IGNORECASE)
    words = cleaned.split()
    filtered = []
    for w in words:
        w_lower = w.lower().rstrip('.,!?;:')
        if w_lower in _STRIP_FILLERS and len(words) > 1:
            continue
        filtered.append(w)
    result = " ".join(filtered).strip()
    result = re.sub(r'\s{2,}', ' ', result)
    return result if result else text


def falcon_validate(raw_text, clean_text, layer, tone="casual", onset_weights=None, language_code="en"):
    """Retired 2026-05-10. L4 Sonnet ET self-validates; L2/L3 GPT-4o quality
    is sufficient without cross-provider QA. Stub matches lavrentiy.py:3420-3428.

    The live body was burning an extra GPT-4o roundtrip per request, doubling
    OpenAI quota usage. Keep the signature so existing call sites compile."""
    return True


def compute_confidence(raw_text, clean_text, falcon_ok, layer=2):
    """Compute intent confidence score (γ) between 0 and 1.

    Factors:
    - Falcon validation (binary meaning check)
    - Length ratio (extreme compression = lower confidence)
    - Layer (higher layers = more aggressive reconstruction = needs more trust)
    """
    if not falcon_ok:
        return 0.3

    raw_words = len(raw_text.split())
    clean_words = len(clean_text.split())

    if raw_words == 0:
        return 0.5

    ratio = clean_words / raw_words
    gamma = 0.85

    if ratio < 0.3:
        gamma -= 0.15
    elif ratio > 1.5:
        gamma -= 0.2

    if layer >= 4:
        gamma -= 0.05

    if raw_words < 4:
        gamma -= 0.1

    return round(max(0.1, min(1.0, gamma)), 2)


def reconstruct_intent(raw_text, tone="casual", layer=2, profile=None,
                       situation="default", mode="FAST",
                       whisper_low_conf=None, whisper_disagreements=None,
                       speech_severity_mod=0.0,
                       paralinguistic_events=None, prosodic_context=None,
                       language_code="en"):
    """Main entry point. Takes raw messy text, returns clean text + confidence.

    Args:
        raw_text: Raw transcription from Whisper or device ASR.
        tone: One of "formal", "professional", "casual", "friend".
        layer: 1=transcribe only, 2=reconstruct, 3=+profile, 4=+stutter.
        profile: Dict with vocabulary, corrections, filler_words, trigger_words, etc.
        situation: "default", "high_stress", or "reading".
        mode: "RAW" (no processing), "FAST" (skip Falcon), "SAFE" (full pipeline).
        whisper_low_conf: Low-confidence segments from Whisper.
        whisper_disagreements: Multi-temp disagreements from Whisper.
        speech_severity_mod: Dynamic severity boost from speech rate analysis.

    Returns:
        dict with: clean, raw, confidence, falcon_ok, ms, mode, tone, layer
    """
    if not client:
        return {"error": "No API key configured", "raw": raw_text, "clean": raw_text,
                "confidence": 0.0, "ms": 0}

    t0 = time.time()
    profile = profile or {}

    if layer <= 1 or mode == "RAW":
        cleaned = strip_disfluencies(raw_text)
        ms = round((time.time() - t0) * 1000)
        return {
            "clean": cleaned, "raw": raw_text, "confidence": 0.95,
            "falcon_ok": True, "ms": ms, "mode": mode, "tone": tone, "layer": layer
        }

    system_prompt = build_prompt(
        raw_text, tone=tone, layer=layer, profile=profile, situation=situation,
        whisper_low_conf=whisper_low_conf, whisper_disagreements=whisper_disagreements,
        speech_severity_mod=speech_severity_mod,
        paralinguistic_events=paralinguistic_events, prosodic_context=prosodic_context,
        language_code=language_code,
    )

    temp = TONE_TEMP.get(tone, 0.3)
    use_model = MODEL_L4 if layer >= 4 else MODEL

    resp = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text}
        ],
        max_tokens=1000,
        temperature=temp
    )
    clean_text = resp.choices[0].message.content.strip()

    falcon_ok = True
    if mode == "SAFE":
        falcon_ok = falcon_validate(
            raw_text, clean_text, layer,
            tone=tone,
            onset_weights=(profile or {}).get("onset_weights"),
            language_code=language_code,
        )
        if not falcon_ok:
            clean_text = strip_disfluencies(raw_text)

    gamma = compute_confidence(raw_text, clean_text, falcon_ok, layer)
    ms = round((time.time() - t0) * 1000)

    return {
        "clean": clean_text,
        "raw": raw_text,
        "confidence": gamma,
        "falcon_ok": falcon_ok,
        "ms": ms,
        "mode": mode,
        "tone": tone,
        "layer": layer,
    }
