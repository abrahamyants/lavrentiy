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

import logging
import os
import re
import time

import openai

try:
    import anthropic
except ImportError:
    # Local runs before `pip install anthropic` keep working on the GPT-4o
    # path; the deployed CF always has it via requirements.txt.
    anthropic = None

import meaning_guard
import profile_terms
from prompt_builder import (
    L2_MAX_REWRITE_ATTEMPTS,
    SITUATION_SEVERITY,
    TONE_TEMP,
    build_completion_prompt,
    build_prompt,
    is_effectively_unchanged,
    run_layer2_rewrite,
)

# ─── Config ───
# Model pinned to a specific snapshot so silent OpenAI version drift can't
# change reconstruction behavior without us noticing. Override via env when
# A/B-testing newer snapshots.
MODEL = os.environ.get("WIM_MODEL", "gpt-4o-2024-11-20")
MODEL_L4 = os.environ.get("WIM_MODEL_L4", "gpt-4o-2024-11-20")
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

# timeout=20s: Cloud Function default is 60s but we want a hard cap well below
# that so a slow OpenAI call doesn't burn the full CF window. max_retries=2:
# transient 5xx/429s self-recover without surfacing to the client.
client = openai.OpenAI(api_key=API_KEY, timeout=20.0, max_retries=2) if API_KEY else None

# ─── L4: Anthropic Sonnet 4.6 extended thinking ───
# Parity with the desktop direct-key path (lavrentiy.py) and WiM device-direct:
# same model, same thinking budget, same max_tokens, same GPT-4o fallback.
# The thinking trace is the validator — Falcon stays retired at L4.
SONNET_THINK_MODEL = os.environ.get("WIM_MODEL_L4_SONNET", "claude-sonnet-4-6")
SONNET_THINK_BUDGET = 8000
SONNET_THINK_MAX_TOKENS = 16000  # must exceed thinking budget

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_KEY:
    for p in [
        os.path.join(os.path.dirname(__file__), "anthropic_key.txt"),
        os.path.join(os.path.dirname(__file__), "..", "..", "anthropic_key.txt"),
    ]:
        if os.path.exists(p):
            ANTHROPIC_KEY = open(p).read().strip()
            break

# timeout=45s: a legitimate Sonnet ET call worst-cases ~30s (see CLOUD_TIMEOUT_SEC
# rationale in lavrentiy.py); 45s plus the 20s GPT-4o fallback still fits the
# CF's 120s window. max_retries=0: a retried ET call can't fit that window —
# the GPT-4o fallback below IS the retry.
anthropic_client = (
    anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=45.0, max_retries=0)
    if (anthropic is not None and ANTHROPIC_KEY) else None
)

# ─── Bilingual filler set ───
_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}


# Mirror of lavrentiy.py NATURAL_REPEATS and DisfluencyFilter.kt NATURAL_REPEATS.
# This copy had neither the allow-list nor the 3+ threshold, so it collapsed
# every doubling: "no no that's not what I meant" came back as "no that's not
# what I meant", "bye bye" as "bye", "ha ha" as "ha". The 2026-07-29 corpus
# reached the same symptom from the prompt side (finding 3) and read it as an
# L2-vs-L4 prompt difference; this filter runs before either prompt and was
# doing it at every layer. Emphasis is meaning.
NATURAL_REPEATS = {
    "had had", "that that", "is is", "was was", "do do",
    "can can", "no no", "bye bye", "so so", "very very",
    "go go", "now now", "come come", "well well",
    "out out", "boo boo", "ha ha", "ho ho",
    "knock knock", "tsk tsk", "aye aye",
    # Emphatic doublings — WiM parity.
    "really really", "many many", "much much", "right right",
    "sure sure", "okay okay", "just just",
    # Russian
    "да да", "нет нет", "ну ну",
}

# Caption boilerplate Whisper emits when it decodes silence — training-data
# residue from subtitled video. A hard block produces exactly this: no airflow,
# no words, and Whisper fills the gap with "thanks for watching".
_CAPTION_ARTIFACT = re.compile(
    r"\b(?:thanks?\s+(?:you\s+)?for\s+watching"
    r"|(?:don'?t\s+forget\s+to|please|like\s+and)\s+subscribe"
    r"|transcribed\s+by[^.,;!?]*|subtitles?\s+by[^.,;!?]*"
    r"|amara\.org|otter\.ai)\b[.,!?]*",
    re.IGNORECASE,
)

# Bracketed markers Whisper emits for the same silence.
_SYSTEM_MARKER = re.compile(
    r"\[(?:blank[_ ]audio|inaudible|music|applause|silence|no[_ ]audio|laughter)\]"
    r"|\[(?:blank[_ ]audio|inaudible|music|applause|silence|no[_ ]audio|laughter)\s*$",
    re.IGNORECASE,
)


def strip_caption_artifacts(text):
    """Remove caption boilerplate and bracketed silence markers.

    Belongs on every path that hands the raw transcript back: the two guard
    refusals and L1/RAW. When the guard rejects a reconstruction because the
    model invented a replacement for a blocked word, falling back to raw is
    right — falling back to raw that still says "thanks for watching" is not.
    Refusing to fabricate and then pasting garbage is the same bad outcome by a
    different route.

    Returns the original when stripping would empty it; an incomplete sentence
    beats an empty paste. Port of DisfluencyFilter.stripCaptionArtifacts, which
    has shipped on the WiM device path since 2026-07-29.
    """
    if not text or not text.strip():
        return text
    stripped = _SYSTEM_MARKER.sub("", text)
    stripped = _CAPTION_ARTIFACT.sub(" ", stripped)
    stripped = re.sub(r'\s{2,}', ' ', stripped).strip()
    return stripped if stripped else text


def _dedup_word(m):
    if f"{m.group(1)} {m.group(1)}".lower() in NATURAL_REPEATS:
        return m.group(0)
    return m.group(1)


def _dedup_phrase(m):
    if m.group(1).lower() in NATURAL_REPEATS:
        return m.group(0)
    return m.group(1)


def strip_disfluencies(text):
    """Remove obvious disfluency artifacts from transcription (zero API cost)."""
    if not text or not text.strip():
        return text
    cleaned = re.sub(r'(\b\w+)-\s+(?:\1-\s+)*', '', text, flags=re.IGNORECASE)
    # 3+ repetitions, not 2+. Two is usually emphasis ("no no", "please please");
    # three is where the speaker was blocked. Matches lavrentiy.py:3063. The
    # [,;:] handling is retained — cloud ASR punctuates repeats ("I, I, I need").
    cleaned = re.sub(
        r'\b(\w+)(?:[,;:]?\s+\1){2,}\b[,;:]?',
        _dedup_word,
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', _dedup_phrase, cleaned, flags=re.IGNORECASE)
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


def complete_partial(partial_text, tone="casual", language_code="en", n=3):
    """Mid-block bridging: given a partial utterance captured when the speaker
    froze mid-sentence, return up to `n` short completion candidates to tap.

    Uses the fast GPT-4o path — the speaker is frozen waiting, so latency beats
    the depth that Sonnet extended thinking would add. Returns a list[str]; empty
    list on no input / no client / parse failure (caller treats empty as no-op)."""
    partial_text = (partial_text or "").strip()
    if not partial_text or client is None:
        return []
    system_prompt = build_completion_prompt(
        partial_text, tone=tone, language_code=language_code, n=n)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": partial_text},
        ],
        max_tokens=200,
        temperature=0.5,
    )
    raw = (resp.choices[0].message.content or "").strip()
    candidates = []
    for line in raw.splitlines():
        c = re.sub(r'^[\s\-\d.)]+', '', line).strip().strip('"').strip()
        if c:
            candidates.append(c)
    return candidates[:n]


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
                       language_code="en", preceding_context=None,
                       script_prep_context=None, compression_ratio_note=None,
                       previous_outputs=None, prior_rejections=None,
                       style_examples=None, window_title=None):
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
    source_raw_text = raw_text

    if layer <= 1 or mode == "RAW":
        # No model runs on this path, so whatever Whisper invented during a
        # block goes straight into the user's text field. The 2026-07-29 corpus
        # only exercised L2 and L4, so this route was never observed failing.
        cleaned = strip_disfluencies(strip_caption_artifacts(raw_text))
        ms = round((time.time() - t0) * 1000)
        return {
            "clean": cleaned, "raw": raw_text, "confidence": 0.95,
            "falcon_ok": True, "ms": ms, "mode": mode, "tone": tone, "layer": layer,
            "model": "local-strip",
        }

    profile_matches = []
    if layer >= 3:
        low_conf_texts = [
            str(segment.get("text", ""))
            for segment in (whisper_low_conf or [])
            if isinstance(segment, dict) and segment.get("text")
        ]
        raw_text, profile_matches = profile_terms.apply_profile_terms(
            raw_text,
            profile,
            low_conf_texts=low_conf_texts,
        )

    system_prompt = build_prompt(
        raw_text, tone=tone, layer=layer, profile=profile, situation=situation,
        whisper_low_conf=whisper_low_conf, whisper_disagreements=whisper_disagreements,
        speech_severity_mod=speech_severity_mod,
        paralinguistic_events=paralinguistic_events, prosodic_context=prosodic_context,
        language_code=language_code,
        preceding_context=preceding_context,
        script_prep_context=script_prep_context,
        compression_ratio_note=compression_ratio_note,
        previous_outputs=previous_outputs,
        prior_rejections=prior_rejections,
        style_examples=style_examples,
        window_title=window_title,
    )

    temp = TONE_TEMP.get(tone, 0.3)
    use_model = MODEL_L4 if layer >= 4 else MODEL
    # L4 clinical reconstructions can run long when the clinical block paints
    # detailed disfluency context; 1000 tokens occasionally truncated mid-sentence.
    # L2/L3 are short rewrites that almost never exceed 1000 tokens, so kept tight
    # to avoid the model padding output.
    max_out = 4000 if layer >= 4 else 1000

    clean_text = ""
    served_model = use_model
    rewrite_attempts = 0

    def _guard_once(candidate):
        return meaning_guard.guard(
            raw_text,
            candidate,
            vocabulary=profile.get("vocabulary"),
        )

    def _log_retry(attempts, candidate, retry_guard):
        logging.warning(
            "Layer %s rewrite rejected on attempt %s: lost=%s "
            "invented=%s unchanged=%s — retrying",
            layer,
            attempts,
            retry_guard.get("lost", []),
            retry_guard.get("invented", []),
            is_effectively_unchanged(raw_text, candidate),
        )

    # L4 clinical → Sonnet 4.6 extended thinking, mirroring lavrentiy.py.
    # It uses the same deterministic guard-and-repair loop as L2/L3.
    # Any API failure or empty final output falls through to GPT-4o below.
    if layer >= 4 and anthropic_client is not None:
        try:
            sonnet_messages = [{"role": "user", "content": raw_text}]

            def _sonnet_rewrite_once(rewrite_messages, _attempt_index):
                msg = anthropic_client.messages.create(
                    model=SONNET_THINK_MODEL,
                    max_tokens=SONNET_THINK_MAX_TOKENS,
                    thinking={"type": "enabled", "budget_tokens": SONNET_THINK_BUDGET},
                    system=system_prompt,
                    messages=rewrite_messages,
                )
                text_blocks = [
                    block.text for block in msg.content
                    if getattr(block, "type", None) == "text"
                ]
                return "\n".join(text_blocks).strip()

            clean_text, rewrite_attempts, _retry_guard = run_layer2_rewrite(
                raw_text,
                sonnet_messages,
                _sonnet_rewrite_once,
                _guard_once,
                on_retry=_log_retry,
                max_attempts=L2_MAX_REWRITE_ATTEMPTS,
            )
            if clean_text:
                served_model = f"{SONNET_THINK_MODEL} (ext-think)"
        except Exception as e:
            logging.warning(
                "Sonnet ext-think failed (%s), falling back to %s",
                str(e)[:120], use_model)
            clean_text = ""

    rewrite_attempts = rewrite_attempts if clean_text else 0
    if not clean_text:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ]

        def _rewrite_once(rewrite_messages, attempt_index):
            resp = client.chat.completions.create(
                model=use_model,
                messages=rewrite_messages,
                max_tokens=max_out,
                temperature=temp if attempt_index == 0 else min(temp, 0.1),
            )
            return (resp.choices[0].message.content or "").strip()

        if layer >= 2:
            clean_text, rewrite_attempts, _retry_guard = run_layer2_rewrite(
                raw_text,
                messages,
                _rewrite_once,
                _guard_once,
                on_retry=_log_retry,
                max_attempts=L2_MAX_REWRITE_ATTEMPTS,
            )
        else:
            clean_text = _rewrite_once(messages, 0)
            rewrite_attempts = 1
        served_model = use_model

    falcon_ok = True
    if mode == "SAFE":
        falcon_ok = falcon_validate(
            raw_text, clean_text, layer,
            tone=tone,
            onset_weights=(profile or {}).get("onset_weights"),
            language_code=language_code,
        )
        if not falcon_ok:
            clean_text = strip_disfluencies(strip_caption_artifacts(raw_text))

    # Deterministic meaning guard. lavrentiy.py has had this for a long time;
    # this path never did, so a signed-in desktop user got no server-side check.
    # WiM Android was NOT in that gap — ReconstructClient.computeRiskFlags has
    # guarded the backend path client-side since 2026-06-03.
    #
    # Always evaluated (it is pure regex, no cost, no latency) so the flags are
    # visible in every mode, but only ACTED on in SAFE. FAST's contract is
    # "give me the reconstruction and get out of the way"; silently swapping in
    # raw text there would change a mode people rely on.
    guard_result = {"ok": True, "lost": [], "invented": []}
    try:
        guard_result = meaning_guard.guard(
            raw_text, clean_text,
            vocabulary=(profile or {}).get("vocabulary"),
        )
        if layer >= 2 and is_effectively_unchanged(raw_text, clean_text):
            guard_result["unchanged"] = True
            guard_result["ok"] = False
        if mode == "SAFE" and not guard_result["ok"]:
            logging.warning(
                "Layer %s repair attempts exhausted: lost=%s invented=%s "
                "unchanged=%s — reconstruction unavailable",
                layer,
                guard_result["lost"], guard_result["invented"],
                guard_result.get("unchanged", False),
            )
            clean_text = strip_disfluencies(strip_caption_artifacts(raw_text))
            falcon_ok = False
    except Exception as e:
        logging.warning("meaning guard failed, passing reconstruction through: %s", e)

    gamma = compute_confidence(source_raw_text, clean_text, falcon_ok, layer)
    ms = round((time.time() - t0) * 1000)

    return {
        "clean": clean_text,
        "raw": source_raw_text,
        "confidence": gamma,
        "falcon_ok": falcon_ok,
        "ms": ms,
        "mode": mode,
        "tone": tone,
        "layer": layer,
        "model": served_model,
        "rewrite_attempts": rewrite_attempts,
        "profile_matches": profile_matches,
        # Surfaced so the desktop console and the WiM bubble can tell the user
        # something was dropped or invented rather than silently handing them a
        # sentence that reads fine.
        "meaning_guard": guard_result,
    }
