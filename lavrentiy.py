"""
LAVRENTIY -- Voice Reconstruction Engine
"We've got a file on you"

Pipeline: Mic -> Whisper -> Reconstruction -> Falcon -> Paste
Layers:  1=Transcribe  2=Reconstruct  3=Profile  4=Stutter
Tones:   casual | professional | friend | formal

F9=talk  F10=tone  F11=layer  F12=stats  F3x3=quit
"""

import sys
import re
import openai
import sounddevice as sd
import soundfile as sf
import keyboard
import pyperclip
import pyautogui
import tempfile
import threading
import numpy
import os
import time
import json
import ctypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from scipy.signal import resample_poly
from math import gcd
from pathlib import Path
from datetime import datetime

# -- Headless mode (pythonw / hidden window) ──────────────────────
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# -- Single-instance enforcement ──────────────────────────────────
mutex_name = "Global\\LAVRENTIY_SINGLE_INSTANCE"
mutex_handle = kernel32.CreateMutexW(None, True, mutex_name)
if kernel32.GetLastError() == 183:
    print("Lavrentiy is already running. Exiting.")
    kernel32.CloseHandle(mutex_handle)
    os._exit(0)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    user32.SetProcessDPIAware()

# -- Configuration ────────────────────────────────────────────────
API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not API_KEY:
    print("ERROR: Set OPENAI_API_KEY environment variable.")
    print("  setx OPENAI_API_KEY sk-proj-...")
    print("  (then open a new terminal)")
    os._exit(1)

LANGUAGE = "en"
PREFERRED_MIC = "C930"
RECORD_KEY = "f9"
TONE_KEY = "f10"
LAYER_KEY = "f11"
MODEL = "gpt-4o-mini"
PROFILE_DIR = Path.home() / ".lavrentiy"
PROFILE_PATH = PROFILE_DIR / "profile.json"
MAX_SESSIONS = 100
DASHBOARD_PORT = 7878
DASHBOARD_PATH = PROFILE_DIR / "dashboard.html"

# -- Phase 2 config ──────────────────────────────────────────────
MODE = "SAFE"                     # RAW | FAST | SAFE (default)
MODES = ["RAW", "FAST", "SAFE"]
LEARN_PROMOTION_THRESHOLD = 2     # candidate recurrences before promotion
MAX_PROFILE_ITEMS = 200           # cap per profile section
HOLD_ON_HIGH_RISK = False         # True = skip paste when risk_flags present
BACKUP_DIR = PROFILE_DIR / "backups"
PROFILE_VERSION = 2

# -- Live preview config ─────────────────────────────────────────
LIVE_PREVIEW_ENABLED = False      # True = stream interim transcripts
PREVIEW_PROVIDER = "none"         # none | deepgram | assemblyai | google
PREVIEW_LANGUAGE = "en"

TONES = ["casual", "professional", "friend", "formal"]
TONE_SHORT = {"casual": "CAS", "professional": "PRO", "friend": "FRD", "formal": "FRM"}
LAYERS = [1, 2, 3, 4]
LAYER_NAMES = {1: "transcribe", 2: "reconstruct", 3: "profile", 4: "stutter"}

client = openai.OpenAI(api_key=API_KEY)

# -- Mic selection ────────────────────────────────────────────────
DEVICE = None
for i, dev in enumerate(sd.query_devices()):
    if PREFERRED_MIC.lower() in dev['name'].lower() and dev['max_input_channels'] > 0:
        DEVICE = i
        break
if DEVICE is None:
    DEVICE = sd.default.device[0]
    print(f"WARNING: {PREFERRED_MIC} not found, using default input")

device_info = sd.query_devices(DEVICE)
NATIVE_RATE = int(device_info['default_samplerate'])
TARGET_RATE = 16000
NEEDS_RESAMPLE = NATIVE_RATE != TARGET_RATE
if NEEDS_RESAMPLE:
    _g = gcd(TARGET_RATE, NATIVE_RATE)
    RESAMPLE_UP = TARGET_RATE // _g
    RESAMPLE_DOWN = NATIVE_RATE // _g

# -- The File (User Profile) ─────────────────────────────────────
# Bilingual filler sets — merged into profile on startup
KNOWN_FILLERS = {
    "en": ["um", "uh", "like", "you know", "I mean", "so", "well", "right",
           "basically", "literally", "actually", "honestly"],
    "ru": ["это", "ну", "вот", "типа", "как бы", "значит", "короче",
           "ладно", "та", "э", "ээ", "слушай"],
}

DEFAULT_PROFILE = {
    "version": PROFILE_VERSION,
    "created": None,
    "trigger_words": [],
    "filler_words": ["um", "uh", "like", "you know", "это", "ну", "вот",
                     "типа", "как бы", "значит", "короче"],
    "corrections": {},
    "vocabulary": [],
    "candidate_corrections": {},
    "candidate_fillers": {},
    "candidate_vocabulary": {},
    "preferences": {"tone": "casual", "layer": 2},
    "sessions": []
}

def load_profile():
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    p = dict(DEFAULT_PROFILE)
    p["created"] = datetime.now().isoformat()
    p["sessions"] = []
    p["corrections"] = {}
    p["trigger_words"] = list(DEFAULT_PROFILE["trigger_words"])
    p["filler_words"] = list(DEFAULT_PROFILE["filler_words"])
    p["vocabulary"] = list(DEFAULT_PROFILE["vocabulary"])
    p["preferences"] = dict(DEFAULT_PROFILE["preferences"])
    return p

def migrate_fillers(prof):
    """Seed known bilingual fillers into existing profiles."""
    existing = {f.lower() for f in prof.get("filler_words", [])}
    added = []
    for lang_fillers in KNOWN_FILLERS.values():
        for filler in lang_fillers:
            if filler.lower() not in existing:
                prof.setdefault("filler_words", []).append(filler)
                existing.add(filler.lower())
                added.append(filler)
    if added:
        save_profile(prof)
    return added

def save_profile(prof):
    PROFILE_DIR.mkdir(exist_ok=True)
    tmp_path = PROFILE_PATH.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(PROFILE_PATH)

def _snapshot_profile(prof):
    """Save timestamped backup. Keep last 5."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"profile_{ts}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)
    for old in sorted(BACKUP_DIR.glob("profile_*.json"))[:-5]:
        old.unlink()

def migrate_profile(prof):
    """Upgrade profile schema to current version."""
    v = prof.get("version", 1)
    if v < PROFILE_VERSION:
        _snapshot_profile(prof)
        prof.setdefault("candidate_corrections", {})
        prof.setdefault("candidate_fillers", {})
        prof.setdefault("candidate_vocabulary", {})
        prof["version"] = PROFILE_VERSION
        save_profile(prof)
    return prof

def log_session(prof, raw, output, tone, layer, decision=None, timings=None):
    entry = {
        "ts": datetime.now().isoformat(),
        "raw": raw,
        "out": output,
        "tone": tone,
        "layer": layer,
        "words": len(output.split()),
        "falcon": decision["falcon_ok"] if decision else True
    }
    if decision:
        entry["decision"] = decision
    if timings:
        entry["timings"] = timings
    prof["sessions"].append(entry)
    if len(prof["sessions"]) > MAX_SESSIONS:
        prof["sessions"] = prof["sessions"][-MAX_SESSIONS:]
    save_profile(prof)

profile = load_profile()
profile = migrate_profile(profile)
_new_fillers = migrate_fillers(profile)
if _new_fillers:
    print(f"Added {len(_new_fillers)} bilingual fillers: {', '.join(_new_fillers)}")

# -- State ────────────────────────────────────────────────────────
recording = []
is_recording = False
stream = None
lock = threading.Lock()
state = 'idle'

current_tone = profile["preferences"].get("tone", "casual")
current_layer = profile["preferences"].get("layer", 2)
current_mode = profile["preferences"].get("mode", MODE)
tap_times = []
target_hwnd = None
last_paste_time = 0
last_stop_time = 0
is_pasting = False
stats = {
    "words": 0, "sessions": 0, "chars": 0,
    "start_time": time.time(),
    "api_calls": 0, "falcon_rejects": 0
}

# -- Live preview state ───────────────────────────────────────────
preview_lock = threading.Lock()
preview_state = {
    "active": False,
    "text": "",
    "final_text": "",
    "updated_at": 0
}
_preview_worker = None

def update_preview_text(text, is_final=False):
    with preview_lock:
        preview_state["text"] = text
        if is_final:
            preview_state["final_text"] = text
        preview_state["updated_at"] = time.time()

def start_preview_stream():
    global _preview_worker
    if not LIVE_PREVIEW_ENABLED or PREVIEW_PROVIDER == "none":
        return
    with preview_lock:
        preview_state["active"] = True
        preview_state["text"] = ""
        preview_state["final_text"] = ""
        preview_state["updated_at"] = time.time()
    # Stub: real providers would start a websocket/streaming worker here
    log("Preview: stream started (stub)", "info")

def stop_preview_stream():
    global _preview_worker
    with preview_lock:
        preview_state["active"] = False
    if _preview_worker and _preview_worker.is_alive():
        _preview_worker = None
    # Stub: real providers would close websocket here

# -- Live console log ─────────────────────────────────────────────
console_log = []
console_id = 0

def log(text, kind="info"):
    global console_id
    console_id += 1
    console_log.append({"id": console_id, "ts": time.time(), "text": text, "kind": kind})
    if len(console_log) > 80:
        console_log.pop(0)
    print(text)

# -- LLM Calls ───────────────────────────────────────────────────
def reconstruct(raw_text, tone, layer, prof):
    """Layer 2+: Rebuild raw transcription into clean output."""
    # Detect if input contains Cyrillic (bilingual speaker)
    has_cyrillic = any('\u0400' <= c <= '\u04ff' for c in raw_text)
    lang_note = " Speaker is bilingual (English/Russian) and may mix languages." if has_cyrillic else ""

    parts = [
        f"Rebuild this raw voice transcription into clean {tone} text.{lang_note}",
        "Fix grammar. Strip filler words (including non-English fillers). Restructure for clarity.",
        "Preserve FULL meaning. Do not summarize or add information.",
        "Output ONLY the reconstructed text."
    ]

    # Always pass filler list at Layer 2+ (bilingual fillers matter everywhere)
    if prof.get("filler_words"):
        parts.append(f"\nStrip these fillers: {', '.join(prof['filler_words'][:25])}")

    if layer >= 3 and prof:
        ctx = []
        if prof.get("vocabulary"):
            ctx.append(f"Preferred terms: {', '.join(prof['vocabulary'][:20])}")
        if prof.get("corrections"):
            pairs = [f"{k}->{v}" for k, v in list(prof["corrections"].items())[:10]]
            ctx.append(f"Known corrections: {'; '.join(pairs)}")
        if ctx:
            parts.append("\nUser context:\n" + "\n".join(ctx))

    if layer >= 4:
        parts.append(
            "\nSpeaker stutters. Repeated syllables/words and blocks "
            "are disfluencies, NOT emphasis. Strip and reconstruct."
        )
        if prof.get("trigger_words"):
            parts.append(f"Trigger words: {', '.join(prof['trigger_words'])}")

    stats["api_calls"] += 1
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "\n".join(parts)},
            {"role": "user", "content": raw_text}
        ],
        max_tokens=1000,
        temperature=0.3
    )
    return resp.choices[0].message.content.strip()


def falcon_validate(raw_text, clean_text, layer):
    """Binary meaning check. Returns True if meaning preserved."""
    prompt = "Does the reconstruction preserve the same meaning? Answer ONLY 'yes' or 'no'."
    if layer >= 4:
        prompt = (
            "Speaker stutters. Repeated syllables are disfluencies, not emphasis. "
            "Does the reconstruction preserve intended meaning? Answer ONLY 'yes' or 'no'."
        )

    stats["api_calls"] += 1
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Original: {raw_text}\nReconstruction: {clean_text}"}
        ],
        max_tokens=5,
        temperature=0
    )
    return "yes" in resp.choices[0].message.content.strip().lower()


# -- Auto-Learn ──────────────────────────────────────────────────
LEARN_EVERY = 3  # run learner every N sessions (Layer 2+)
_learn_counter = 0
learn_events = []  # [{ts, type, value}, ...]
learn_status = {"last_run": None, "total_learned": 0, "next_in": LEARN_EVERY}

def learn_from_sessions(prof):
    """Analyze recent raw→output pairs and extract patterns."""
    sessions = [s for s in prof.get("sessions", [])
                if s.get("layer", 1) >= 2 and s.get("raw") != s.get("out")]
    recent = sessions[-LEARN_EVERY:]
    if not recent:
        return

    pairs = "\n".join(
        f"Raw: {s['raw']}\nOut: {s['out']}" for s in recent
    )

    stats["api_calls"] += 1
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "Analyze these voice transcription pairs (raw speech → cleaned output). "
                    "Extract patterns:\n"
                    "1. corrections: recurring words misheard by speech-to-text that map to "
                    "different intended words (e.g. \"Duncan\" → \"Dankeschön\"). Only include "
                    "clear, confident mappings.\n"
                    "2. fillers: filler words/sounds the speaker uses IN ANY LANGUAGE "
                    "(e.g. English: um, uh, like, you know; Russian: это, ну, вот, типа, как бы). "
                    "Speaker is bilingual. Only words that appear as filler, not meaningful content.\n"
                    "3. vocabulary: domain-specific or preferred terms the speaker consistently uses.\n"
                    "Return ONLY valid JSON: {\"corrections\": {}, \"fillers\": [], \"vocabulary\": []}\n"
                    "If nothing to extract, return empty collections. Be conservative — only "
                    "include patterns you're confident about."
                )},
                {"role": "user", "content": pairs}
            ],
            max_tokens=300,
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        learnings = json.loads(text)
    except (json.JSONDecodeError, Exception) as e:
        log(f"Learn: parse failed ({e})", "error")
        return

    promoted = 0
    now = datetime.now().isoformat()

    # Corrections → candidates → promote
    existing_corr = {k.lower() for k in prof.get("corrections", {})}
    cand_corr = prof.setdefault("candidate_corrections", {})
    for wrong, right in learnings.get("corrections", {}).items():
        key = wrong.lower()
        if key in existing_corr:
            continue
        if key in cand_corr:
            cand_corr[key]["count"] += 1
        else:
            cand_corr[key] = {"right": right, "count": 1}
        if cand_corr[key]["count"] >= LEARN_PROMOTION_THRESHOLD:
            if len(prof.get("corrections", {})) < MAX_PROFILE_ITEMS:
                prof.setdefault("corrections", {})[wrong] = cand_corr[key]["right"]
            del cand_corr[key]
            learn_events.append({"ts": now, "type": "correction", "value": f"{wrong} → {right}"})
            log(f"Promoted: \"{wrong}\" → \"{right}\"", "info")
            promoted += 1
        else:
            learn_events.append({"ts": now, "type": "candidate", "value": f"{wrong} → {right} ({cand_corr[key]['count']}/{LEARN_PROMOTION_THRESHOLD})"})

    # Fillers → candidates → promote
    existing_fillers = {f.lower() for f in prof.get("filler_words", [])}
    cand_fill = prof.setdefault("candidate_fillers", {})
    for filler in learnings.get("fillers", []):
        key = filler.lower()
        if key in existing_fillers:
            continue
        cand_fill[key] = cand_fill.get(key, 0) + 1
        if cand_fill[key] >= LEARN_PROMOTION_THRESHOLD:
            if len(prof.get("filler_words", [])) < MAX_PROFILE_ITEMS:
                prof.setdefault("filler_words", []).append(key)
            del cand_fill[key]
            learn_events.append({"ts": now, "type": "filler", "value": key})
            log(f"Promoted filler: \"{filler}\"", "info")
            promoted += 1
        else:
            learn_events.append({"ts": now, "type": "candidate", "value": f"filler: {key} ({cand_fill[key]}/{LEARN_PROMOTION_THRESHOLD})"})

    # Vocabulary → candidates → promote
    existing_vocab = {v.lower() for v in prof.get("vocabulary", [])}
    cand_vocab = prof.setdefault("candidate_vocabulary", {})
    for term in learnings.get("vocabulary", []):
        key = term.lower()
        if key in existing_vocab:
            continue
        cand_vocab[key] = cand_vocab.get(key, 0) + 1
        if cand_vocab[key] >= LEARN_PROMOTION_THRESHOLD:
            if len(prof.get("vocabulary", [])) < MAX_PROFILE_ITEMS:
                prof.setdefault("vocabulary", []).append(term)
            del cand_vocab[key]
            learn_events.append({"ts": now, "type": "vocab", "value": term})
            log(f"Promoted vocab: \"{term}\"", "info")
            promoted += 1
        else:
            learn_events.append({"ts": now, "type": "candidate", "value": f"vocab: {term} ({cand_vocab[key]}/{LEARN_PROMOTION_THRESHOLD})"})

    learn_status["last_run"] = now
    if promoted:
        learn_status["total_learned"] += promoted
    else:
        log("Learn: no promotions this cycle", "info")
    save_profile(prof)  # always save — candidate counts changed

    if len(learn_events) > 50:
        learn_events[:] = learn_events[-50:]


# -- Trigger Word Detection ───────────────────────────────────────
# Regex: catch "Co-Co-Coca-Cola", "I I I want", "th-th-the", "b-b-but"
_REPEAT_WORD = re.compile(
    r'\b(\w+(?:\s+|[-])){1,5}\1{0}\w*\b', re.IGNORECASE
)
# Hyphenated stutters: "co-co-coca", "b-b-but", "th-th-the"
_HYPHEN_STUTTER = re.compile(
    r'\b(\w{1,4})[-]\1[-]?(\w+)\b', re.IGNORECASE
)
# Repeated words: "I I I want", "the the the dog"
_WORD_REPEAT = re.compile(
    r'\b(\w+)(?:\s+\1){1,}\s+(\w+)', re.IGNORECASE
)

def detect_triggers_regex(raw_text):
    """Fast, free trigger word detection from raw transcription patterns."""
    triggers = set()

    # "b-b-but" → "but", "co-co-coca" → "coca" (partial, LLM resolves full word)
    for m in _HYPHEN_STUTTER.finditer(raw_text):
        intended = m.group(1) + m.group(2)
        triggers.add(intended.lower())

    # "I I I want" → "I", "the the dog" → "the"
    for m in _WORD_REPEAT.finditer(raw_text):
        repeated_word = m.group(1)
        if repeated_word.lower() not in {'um', 'uh', 'like', 'so', 'and', 'or', 'but',
                                          'ну', 'это', 'вот', 'а', 'и'}:
            triggers.add(repeated_word.lower())

    return triggers


def detect_triggers_llm(raw_text, output, prof):
    """LLM-assisted trigger word detection. Async, Layer 4 only."""
    stats["api_calls"] += 1
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "The speaker stutters. Analyze this raw voice transcription and its "
                    "clean reconstruction. Identify TRIGGER WORDS — specific words the "
                    "speaker stuttered on (repeated syllables, blocks, prolongations).\n"
                    "Examples of stuttering patterns in raw text:\n"
                    "- 'Co-Co-Coca-Cola' → trigger word: 'Coca-Cola'\n"
                    "- 'I I I want' → trigger word: 'I'\n"
                    "- 'th-th-the' → trigger word: 'the'\n"
                    "- Long pause then word = block → that word is a trigger\n"
                    "- Word avoidance (speaker says synonym instead) = possible trigger\n\n"
                    "Return ONLY valid JSON: {\"trigger_words\": [\"word1\", \"word2\"]}\n"
                    "If no stuttering detected, return {\"trigger_words\": []}\n"
                    "Be conservative — only include words with clear evidence of disfluency."
                )},
                {"role": "user", "content": f"Raw: {raw_text}\nClean: {output}"}
            ],
            max_tokens=150,
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return set(w.lower() for w in result.get("trigger_words", []))
    except Exception as e:
        log(f"Trigger detect failed: {e}", "error")
        return set()


def add_trigger_words(new_triggers, prof):
    """Merge newly detected trigger words into profile."""
    existing = {w.lower() for w in prof.get("trigger_words", [])}
    added = []
    for word in new_triggers:
        if word.lower() not in existing and len(word) > 1:
            prof.setdefault("trigger_words", []).append(word)
            existing.add(word.lower())
            learn_events.append({
                "ts": datetime.now().isoformat(),
                "type": "trigger",
                "value": word
            })
            log(f"Trigger detected: \"{word}\"", "info")
            added.append(word)
    if added:
        save_profile(prof)
    return added


# -- Audio ────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    if is_recording:
        with lock:
            recording.append(indata.copy())

def start_recording():
    global is_recording, recording, stream, target_hwnd, state
    with lock:
        if is_recording:
            return
        recording = []
        is_recording = True
        state = 'recording'
    target_hwnd = user32.GetForegroundWindow()
    log("Recording...", "rec")
    try:
        start_preview_stream()
    except Exception as e:
        log(f"Preview start failed: {e}", "error")
    try:
        stream = sd.InputStream(samplerate=NATIVE_RATE, channels=1,
                                device=DEVICE, callback=audio_callback)
        stream.start()
    except Exception as e:
        log(f"Stream error: {e}", "error")
        with lock:
            is_recording = False
            state = 'error'
        threading.Timer(3, lambda: set_state('idle')).start()

def stop_recording():
    global is_recording, stream, state, last_stop_time
    now = time.time()
    if now - last_stop_time < 1.0:
        return
    last_stop_time = now
    with lock:
        if not is_recording:
            return
        is_recording = False
        state = 'processing'
        s = stream
        stream = None
    if s:
        s.stop()
        s.close()
    try:
        stop_preview_stream()
    except Exception as e:
        log(f"Preview stop failed: {e}", "error")
    log("Processing...", "info")
    threading.Thread(target=pipeline, daemon=True).start()

def set_state(s):
    global state
    state = s

_DANGLING = re.compile(r'(?:,|\band\s*$|\bor\s*$|\bbut\s*$|\.{2}(?!\.)|\bthe\s*$)', re.IGNORECASE)

def compute_risk_flags(raw_text, clean_text, falcon_ok, used_fallback, layer):
    """Deterministic risk flags — no LLM calls."""
    flags = []
    if not falcon_ok:
        flags.append("validator_reject")
    if used_fallback:
        flags.append("reconstruct_fallback")
    if clean_text and layer > 1:
        cw = len(clean_text.split())
        if cw < 2:
            flags.append("very_short_output")
        rw = len(raw_text.split())
        if rw > 0 and cw > 0:
            ratio = rw / cw
            inv = cw / rw
            if ratio > 3.0 or inv > 2.0:
                flags.append("large_length_delta")
        if _DANGLING.search(clean_text.rstrip()):
            flags.append("contains_unfinished_fragment")
    return flags

def make_decision(falcon_ok, layer, used_fallback, risk_flags):
    """Build decision record for this pipeline run."""
    if current_mode == "RAW" or layer == 1:
        decision = "paste_raw"
    elif used_fallback:
        decision = "paste_raw"
    elif current_mode == "FAST":
        decision = "paste_clean"
    else:  # SAFE
        decision = "paste_clean" if falcon_ok else "paste_raw"
    if HOLD_ON_HIGH_RISK and risk_flags:
        decision = "hold"
    return {
        "mode": current_mode, "falcon_ok": falcon_ok,
        "risk_flags": risk_flags, "used_fallback": used_fallback,
        "decision": decision
    }

# -- Pipeline ─────────────────────────────────────────────────────
def pipeline():
    global state
    with lock:
        if not recording:
            state = 'idle'
            return
        frames = list(recording)
        recording.clear()

    audio_data = numpy.concatenate(frames, axis=0).flatten()
    if NEEDS_RESAMPLE:
        audio_data = resample_poly(audio_data, RESAMPLE_UP, RESAMPLE_DOWN)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_data, TARGET_RATE)
    tmp.close()

    try:
        # Step 1: Whisper
        t0 = time.time()
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f, language=LANGUAGE
            )
        raw_text = result.text.strip()
        t_asr = time.time()
        if not raw_text:
            state = 'idle'
            return

        used_fallback = False
        clean_text = None
        falcon_ok = True
        t_recon = t_asr
        t_val = t_asr

        if current_layer > 1 and current_mode != "RAW":
            log(f"Raw: \"{raw_text}\"", "raw")

            # Step 2: Reconstruct
            try:
                clean_text = reconstruct(raw_text, current_tone, current_layer, profile)
            except Exception as e:
                log(f"Reconstruct failed ({e}) -- using raw", "error")
                used_fallback = True
            t_recon = time.time()

            # Step 3: Falcon (SAFE mode only, skip if fallback)
            if current_mode == "SAFE" and clean_text and not used_fallback:
                try:
                    falcon_ok = falcon_validate(raw_text, clean_text, current_layer)
                except Exception:
                    falcon_ok = True
                if not falcon_ok:
                    stats["falcon_rejects"] += 1
                    log("Falcon: REJECTED -- using raw", "error")
            t_val = time.time()

        # Decision
        risk_flags = compute_risk_flags(raw_text, clean_text, falcon_ok, used_fallback, current_layer)
        decision = make_decision(falcon_ok, current_layer, used_fallback, risk_flags)
        output = clean_text if (decision["decision"] == "paste_clean" and clean_text) else raw_text
        timings = {
            "asr_ms": round((t_asr - t0) * 1000),
            "reconstruct_ms": round((t_recon - t_asr) * 1000),
            "validate_ms": round((t_val - t_recon) * 1000),
            "total_ms": round((t_val - t0) * 1000)
        }

        wc = len(output.split())
        tone_tag = TONE_SHORT.get(current_tone, "???")
        if current_layer > 1 and current_mode != "RAW":
            log(f"-> \"{output}\"  [{wc}w] ({tone_tag})", "out")
        else:
            log(f"-> \"{output}\"  [{wc}w]", "out")
        flags_tag = f" flags:[{','.join(decision['risk_flags'])}]" if decision['risk_flags'] else ""
        log(f"[{decision['mode']}] {decision['decision']} | {timings['total_ms']}ms (asr:{timings['asr_ms']} recon:{timings['reconstruct_ms']} val:{timings['validate_ms']}){flags_tag}", "info")

        # Paste or hold
        if decision["decision"] == "hold":
            log("HELD — high-risk output not pasted", "error")
        else:
            stats["words"] += wc
            stats["chars"] += len(output)
            stats["sessions"] += 1
            paste(output)
        log_session(profile, raw_text, output, current_tone, current_layer, decision, timings)
        state = 'idle'

        # Step 5: Trigger word detection (Layer 4)
        if current_layer >= 4:
            regex_triggers = detect_triggers_regex(raw_text)
            if regex_triggers:
                add_trigger_words(regex_triggers, profile)
            threading.Thread(
                target=lambda: add_trigger_words(
                    detect_triggers_llm(raw_text, output, profile), profile
                ), daemon=True
            ).start()

        # Step 6: Auto-learn (async, Layer 2+ only)
        if current_layer >= 2:
            global _learn_counter
            _learn_counter += 1
            learn_status["next_in"] = max(0, LEARN_EVERY - _learn_counter)
            if _learn_counter >= LEARN_EVERY:
                _learn_counter = 0
                learn_status["next_in"] = LEARN_EVERY
                threading.Thread(target=learn_from_sessions, args=(profile,), daemon=True).start()

    except Exception as e:
        log(f"Error: {e}", "error")
        state = 'error'
        threading.Timer(3, lambda: set_state('idle')).start()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def paste(text):
    """Copy to clipboard + restore focus + Ctrl+V."""
    global last_paste_time, is_pasting
    now = time.time()
    if now - last_paste_time < 1.0 or is_pasting:
        return
    last_paste_time = now
    is_pasting = True
    try:
        pyperclip.copy(text + " ")
        for key in ('alt', 'ctrl'):
            try:
                keyboard.release(key)
            except Exception:
                pass
        if target_hwnd:
            for _ in range(5):
                if user32.SetForegroundWindow(target_hwnd):
                    break
                time.sleep(0.05)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
    finally:
        is_pasting = False

# -- Tone/Layer/Mode setters (for dashboard) ──────────────────────
def set_tone(tone):
    global current_tone
    if tone in TONES:
        current_tone = tone
        profile["preferences"]["tone"] = current_tone
        save_profile(profile)
        log(f"Tone: {current_tone}", "info")

def set_layer(layer):
    global current_layer
    if layer in LAYERS:
        current_layer = layer
        profile["preferences"]["layer"] = current_layer
        save_profile(profile)
        log(f"Layer: {current_layer} ({LAYER_NAMES[current_layer]})", "info")

def set_mode(mode):
    global current_mode
    if mode in MODES:
        current_mode = mode
        profile["preferences"]["mode"] = current_mode
        save_profile(profile)
        log(f"Mode: {current_mode}", "info")

# -- Dashboard HTTP server ────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/':
            self._serve_file(DASHBOARD_PATH, 'text/html')
        elif self.path == '/api/state':
            self._json({
                'state': state,
                'tone': current_tone,
                'layer': current_layer,
                'layer_name': LAYER_NAMES.get(current_layer, '?'),
                'mode': current_mode,
                'stats': stats
            })
        elif self.path == '/api/profile':
            self._json(profile)
        elif self.path == '/api/sessions':
            self._json(list(reversed(profile.get('sessions', [])[-50:])))
        elif self.path == '/api/log':
            self._json(console_log)
        elif self.path == '/api/learn':
            self._json({
                'status': learn_status,
                'events': learn_events,
                'totals': {
                    'corrections': len(profile.get('corrections', {})),
                    'fillers': len(profile.get('filler_words', [])),
                    'vocabulary': len(profile.get('vocabulary', [])),
                    'triggers': len(profile.get('trigger_words', [])),
                    'candidates': {
                        'corrections': len(profile.get('candidate_corrections', {})),
                        'fillers': len(profile.get('candidate_fillers', {})),
                        'vocabulary': len(profile.get('candidate_vocabulary', {}))
                    }
                }
            })
        elif self.path == '/api/preview':
            with preview_lock:
                self._json({
                    'enabled': LIVE_PREVIEW_ENABLED,
                    'active': preview_state['active'],
                    'text': preview_state['text'],
                    'final_text': preview_state['final_text'],
                    'updated_at': preview_state['updated_at']
                })
        else:
            self.send_error(404)

    def do_POST(self):
        body = self._read_body()
        if self.path == '/api/tone':
            if body and isinstance(body.get('tone'), str):
                set_tone(body['tone'])
            self._json({'tone': current_tone})
        elif self.path == '/api/layer':
            if body and 'layer' in body:
                try:
                    set_layer(int(body['layer']))
                except (ValueError, TypeError):
                    pass
            self._json({'layer': current_layer, 'layer_name': LAYER_NAMES.get(current_layer, '?')})
        elif self.path == '/api/mode':
            if body and isinstance(body.get('mode'), str):
                set_mode(body['mode'].upper())
            self._json({'mode': current_mode})
        elif self.path == '/api/profile':
            if body and isinstance(body, dict):
                _MAX_ITEMS, _MAX_LEN = 200, 100
                for key in ('trigger_words', 'filler_words', 'vocabulary'):
                    if key in body and isinstance(body[key], list):
                        profile[key] = [str(v)[:_MAX_LEN] for v in body[key][:_MAX_ITEMS]
                                        if isinstance(v, str)]
                if 'corrections' in body and isinstance(body['corrections'], dict):
                    profile['corrections'] = {
                        str(k)[:_MAX_LEN]: str(v)[:_MAX_LEN]
                        for k, v in list(body['corrections'].items())[:_MAX_ITEMS]
                        if isinstance(k, str) and isinstance(v, str)
                    }
                save_profile(profile)
            self._json({'ok': True})
        else:
            self.send_error(404)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0 or length > 1_000_000:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return None

    def _json(self, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path, content_type):
        try:
            with open(path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', f'{content_type}; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, 'Dashboard not found')

def run_dashboard():
    try:
        server = HTTPServer(('127.0.0.1', DASHBOARD_PORT), DashboardHandler)
        server.serve_forever()
    except OSError as e:
        print(f"  Dashboard server failed: {e}")

# -- Hotkeys ──────────────────────────────────────────────────────
def cycle_tone():
    global current_tone
    idx = TONES.index(current_tone)
    current_tone = TONES[(idx + 1) % len(TONES)]
    profile["preferences"]["tone"] = current_tone
    save_profile(profile)
    log(f"Tone: {current_tone}", "info")

def cycle_layer():
    global current_layer
    idx = LAYERS.index(current_layer)
    current_layer = LAYERS[(idx + 1) % len(LAYERS)]
    profile["preferences"]["layer"] = current_layer
    save_profile(profile)
    log(f"Layer: {current_layer} ({LAYER_NAMES[current_layer]})", "info")

def print_stats():
    elapsed = (time.time() - stats["start_time"]) / 60
    wpm = stats["words"] / elapsed if elapsed > 0 else 0
    print(f"\n--- LAVRENTIY ---")
    print(f"Sessions:       {stats['sessions']}")
    print(f"Words:          {stats['words']}")
    print(f"API calls:      {stats['api_calls']}")
    print(f"Falcon rejects: {stats['falcon_rejects']}")
    print(f"Uptime:         {elapsed:.1f} min")
    print(f"WPM:            {wpm:.0f}")
    print(f"Layer:          {current_layer} ({LAYER_NAMES[current_layer]})")
    print(f"Tone:           {current_tone}")
    print(f"Profile:        {PROFILE_PATH}")
    print(f"-----------------\n")

def on_key_event(event):
    global tap_times

    # Block all hook events while pasting to prevent interference
    if is_pasting:
        return

    # Only process KEY_DOWN for non-record keys
    if event.event_type != keyboard.KEY_DOWN and event.name != RECORD_KEY:
        return

    if event.name == 'f12' and event.event_type == keyboard.KEY_DOWN:
        print_stats()
        return

    if event.name == TONE_KEY and event.event_type == keyboard.KEY_DOWN:
        cycle_tone()
        return

    if event.name == LAYER_KEY and event.event_type == keyboard.KEY_DOWN:
        cycle_layer()
        return

    if event.name == 'f3' and event.event_type == keyboard.KEY_DOWN:
        now = time.time()
        tap_times = [t for t in tap_times if now - t < 0.8]
        tap_times.append(now)
        if len(tap_times) == 3:
            print("Lavrentiy out.")
            kernel32.CloseHandle(mutex_handle)
            os._exit(0)
        return

    if event.name == RECORD_KEY:
        if event.event_type == keyboard.KEY_DOWN:
            start_recording()
        elif event.event_type == keyboard.KEY_UP:
            stop_recording()

# -- Keep-alive (replaces tkinter indicator) ──────────────────────
def keep_alive():
    """Block main thread so the script stays running."""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

# -- Main ─────────────────────────────────────────────────────────
print(f"LAVRENTIY v0.1 | L{current_layer} {current_tone}")
print(f"Mic: {device_info['name']} | {NATIVE_RATE}Hz")
print(f"F9=talk  F10=tone  F11=layer  F12=stats  F3x3=quit")
print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
print(f"\"Lavrentiy does his best. Check your shit before you send it.\"")
print()

# Start dashboard server
threading.Thread(target=run_dashboard, daemon=True).start()

keyboard.hook(on_key_event)
keep_alive()
