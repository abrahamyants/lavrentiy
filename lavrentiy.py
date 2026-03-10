"""
LAVRENTIY -- Voice Reconstruction Engine
"We've got a file on you"

Pipeline: Mic -> Whisper -> Reconstruction -> Falcon -> Paste
Layers:  1=Transcribe  2=Reconstruct  3=Profile  4=Stutter
Tones:   casual | professional | friend | formal

F9=talk  F10=tone  F11=layer  F12=stats  F3x3=quit
"""

import sys
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
DEFAULT_PROFILE = {
    "version": 1,
    "created": None,
    "trigger_words": [],
    "filler_words": ["um", "uh", "like", "you know"],
    "corrections": {},
    "vocabulary": [],
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

def save_profile(prof):
    PROFILE_DIR.mkdir(exist_ok=True)
    with open(PROFILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)

def log_session(prof, raw, output, tone, layer, falcon_ok):
    prof["sessions"].append({
        "ts": datetime.now().isoformat(),
        "raw": raw,
        "out": output,
        "tone": tone,
        "layer": layer,
        "words": len(output.split()),
        "falcon": falcon_ok
    })
    if len(prof["sessions"]) > MAX_SESSIONS:
        prof["sessions"] = prof["sessions"][-MAX_SESSIONS:]
    save_profile(prof)

profile = load_profile()

# -- State ────────────────────────────────────────────────────────
recording = []
is_recording = False
stream = None
lock = threading.Lock()
state = 'idle'

current_tone = profile["preferences"].get("tone", "casual")
current_layer = profile["preferences"].get("layer", 2)
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
    parts = [
        f"Rebuild this raw voice transcription into clean {tone} text.",
        "Fix grammar. Strip filler words. Restructure for clarity.",
        "Preserve FULL meaning. Do not summarize or add information.",
        "Output ONLY the reconstructed text."
    ]

    if layer >= 3 and prof:
        ctx = []
        if prof.get("filler_words"):
            ctx.append(f"Strip these fillers: {', '.join(prof['filler_words'])}")
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
                    "2. fillers: filler words/sounds the speaker uses (e.g. um, uh, like, you know, "
                    "это). Only words that appear as filler, not meaningful content.\n"
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

    changed = False
    existing_corr = prof.get("corrections", {})
    for wrong, right in learnings.get("corrections", {}).items():
        if wrong.lower() not in {k.lower() for k in existing_corr}:
            prof.setdefault("corrections", {})[wrong] = right
            log(f"Learned: \"{wrong}\" → \"{right}\"", "info")
            changed = True

    existing_fillers = {f.lower() for f in prof.get("filler_words", [])}
    for filler in learnings.get("fillers", []):
        if filler.lower() not in existing_fillers:
            prof.setdefault("filler_words", []).append(filler.lower())
            log(f"Learned filler: \"{filler}\"", "info")
            changed = True

    existing_vocab = {v.lower() for v in prof.get("vocabulary", [])}
    for term in learnings.get("vocabulary", []):
        if term.lower() not in existing_vocab:
            prof.setdefault("vocabulary", []).append(term)
            log(f"Learned vocab: \"{term}\"", "info")
            changed = True

    if changed:
        save_profile(prof)
    else:
        log("Learn: no new patterns", "info")


# -- Audio ────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    if is_recording:
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
    log("Processing...", "info")
    threading.Thread(target=pipeline, daemon=True).start()

def set_state(s):
    global state
    state = s

# -- Pipeline ─────────────────────────────────────────────────────
def pipeline():
    global state
    if not recording:
        state = 'idle'
        return

    audio_data = numpy.concatenate(recording, axis=0).flatten()
    if NEEDS_RESAMPLE:
        audio_data = resample_poly(audio_data, RESAMPLE_UP, RESAMPLE_DOWN)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_data, TARGET_RATE)
    tmp.close()

    try:
        # Step 1: Whisper
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f, language=LANGUAGE
            )
        raw_text = result.text.strip()
        if not raw_text:
            state = 'idle'
            return

        # Layer 1: pure transcription (KJU mode)
        if current_layer == 1:
            output = raw_text
            falcon_ok = True
            log(f"-> \"{output}\"  [{len(output.split())}w]", "out")
        else:
            # TurboTax trick: show raw first
            log(f"Raw: \"{raw_text}\"", "raw")

            # Step 2: Reconstruct
            try:
                output = reconstruct(raw_text, current_tone, current_layer, profile)
            except Exception as e:
                log(f"Reconstruct failed ({e}) -- using raw", "error")
                output = raw_text
                falcon_ok = True
                state = 'idle'
                paste(output)
                log_session(profile, raw_text, output, current_tone, current_layer, True)
                return

            # Step 3: Falcon
            try:
                falcon_ok = falcon_validate(raw_text, output, current_layer)
            except Exception:
                falcon_ok = True  # degrade gracefully

            if not falcon_ok:
                stats["falcon_rejects"] += 1
                log("Falcon: REJECTED -- using raw", "error")
                output = raw_text

            tone_tag = TONE_SHORT.get(current_tone, "???")
            log(f"-> \"{output}\"  [{len(output.split())}w] ({tone_tag})", "out")

        # Step 4: Paste
        stats["words"] += len(output.split())
        stats["chars"] += len(output)
        stats["sessions"] += 1
        log_session(profile, raw_text, output, current_tone, current_layer, falcon_ok)
        paste(output)
        state = 'idle'

        # Step 5: Auto-learn (async, Layer 2+ only)
        if current_layer >= 2:
            global _learn_counter
            _learn_counter += 1
            if _learn_counter >= LEARN_EVERY:
                _learn_counter = 0
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

# -- Tone/Layer setters (for dashboard) ───────────────────────────
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
                'stats': stats
            })
        elif self.path == '/api/profile':
            self._json(profile)
        elif self.path == '/api/sessions':
            self._json(list(reversed(profile.get('sessions', [])[-50:])))
        elif self.path == '/api/log':
            self._json(console_log)
        else:
            self.send_error(404)

    def do_POST(self):
        body = self._read_body()
        if self.path == '/api/tone':
            if body and 'tone' in body:
                set_tone(body['tone'])
            self._json({'tone': current_tone})
        elif self.path == '/api/layer':
            if body and 'layer' in body:
                set_layer(int(body['layer']))
            self._json({'layer': current_layer, 'layer_name': LAYER_NAMES.get(current_layer, '?')})
        elif self.path == '/api/profile':
            if body:
                for key in ('trigger_words', 'filler_words', 'vocabulary', 'corrections'):
                    if key in body:
                        profile[key] = body[key]
                save_profile(profile)
            self._json({'ok': True})
        else:
            self.send_error(404)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
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
