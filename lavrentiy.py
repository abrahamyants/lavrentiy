"""
LAVRENTIY -- Voice Reconstruction Engine
"We've got a file on you"

Pipeline: Mic -> Whisper -> Reconstruction -> Falcon -> Paste
Layers:  1=Transcribe  2=Reconstruct  3=Profile  4=Stutter  5=Paralinguistic
Tones:   casual | professional | friend | formal

Defaults: F9=talk  F10=tone  F11=layer  F12=stats  F3x3=quit  (rebindable)
"""

import sys
import os
# Embedded Python distributions (portable build) don't auto-add the script's
# directory to sys.path — explicitly add it so sibling modules
# (local.whisper_local) can be imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re
import openai
import sounddevice as sd
import soundfile as sf
import keyboard
import pyperclip
import pyautogui
# Disable PyAutoGUI's corner-of-screen fail-safe: it aborts paste() if the mouse
# happens to be in a screen corner. F3×3 is the actual quit hotkey for this engine.
pyautogui.FAILSAFE = False
import tempfile
import threading
import numpy
import os
import time
import json
import sqlite3
import ctypes
import shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from scipy.signal import resample_poly, butter, filtfilt
from math import gcd
from pathlib import Path
from datetime import datetime, timedelta

# -- Headless mode (pythonw / hidden window) ──────────────────────
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# -- Lifecycle audit logger ────────────────────────────────────────
# Writes a one-line entry every time the engine process starts. Records PID,
# parent PID, command line, time. Survives crashes (line-buffered append).
# Lets us correlate "engine died" events with what actually launched the
# replacement instance — desktop.py wrapper? user double-click? something else?
try:
    import datetime as _dt
    _lifecycle_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_lifecycle.log")
    _ppid = os.getppid() if hasattr(os, "getppid") else -1
    with open(_lifecycle_log, "a", encoding="utf-8") as _f:
        _f.write(f"[{_dt.datetime.now().isoformat(timespec='seconds')}] STARTUP pid={os.getpid()} ppid={_ppid} argv={sys.argv}\n")
        _f.flush()
    # Also register an exit hook so we know when this PID went away cleanly.
    import atexit as _atexit
    def _log_exit():
        try:
            with open(_lifecycle_log, "a", encoding="utf-8") as f:
                f.write(f"[{_dt.datetime.now().isoformat(timespec='seconds')}] EXIT pid={os.getpid()} (atexit)\n")
        except Exception:
            pass
    _atexit.register(_log_exit)
except Exception:
    pass


# -- Single-instance enforcement ──────────────────────────────────
def _check_existing_engine():
    """Return True if a healthy engine is already serving on DASHBOARD_PORT.
    Generous 5s timeout — during a long LLM call the /api/state endpoint can
    be queued behind the cloud round-trip. A 2s timeout was producing false
    negatives that triggered the (now-removed) kill-all-pythonw nuclear path
    and made running engines suicide on near-simultaneous launches."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:7878/api/state", timeout=5)
        return resp.status == 200
    except Exception:
        return False

def _kill_engine_on_port(port):
    """Kill ONLY the PID currently listening on the given port. Safe — does
    not touch unrelated pythonw.exe processes. Returns True if a kill ran.

    Replaces the prior `_kill_stale_pythonw()` which ran
    `taskkill /IM pythonw.exe /F` and nuked every pythonw on the system
    (including the desktop wrapper and any sibling tooling), causing the
    engine to suicide whenever a near-simultaneous launch hit the mutex."""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pid = parts[-1] if parts else ""
                if pid.isdigit():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False, timeout=5,
                    )
                    time.sleep(1)
                    return True
    except Exception:
        pass
    return False

mutex_name = "Global\\LAVRENTIY_SINGLE_INSTANCE"
mutex_handle = kernel32.CreateMutexW(None, True, mutex_name)
if kernel32.GetLastError() == 183:
    if _check_existing_engine():
        print("Lavrentiy is already running. Exiting.")
        kernel32.CloseHandle(mutex_handle)
        os._exit(0)
    else:
        print("Stale mutex detected (no healthy engine). Cleaning up port 7878 only...")
        kernel32.CloseHandle(mutex_handle)
        _kill_engine_on_port(7878)
        mutex_handle = kernel32.CreateMutexW(None, True, mutex_name)
        if kernel32.GetLastError() == 183:
            print("Could not reclaim mutex after cleanup. Exiting.")
            kernel32.CloseHandle(mutex_handle)
            os._exit(1)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    user32.SetProcessDPIAware()

# -- Configuration ────────────────────────────────────────────────
API_KEY = ""
_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")
if os.path.exists(_key_file):
    API_KEY = open(_key_file, "r").read().strip()
if not API_KEY:
    API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not API_KEY:
    try:
        print("WARNING: No local API key found. Google Sign-In required for reconstruction.")
        print("  Or: put your key in api_key.txt / set OPENAI_API_KEY env var")
    except Exception:
        pass

# Anthropic key — used for cross-vendor Falcon validation (Claude Haiku 4.5).
# Optional: if not set, falcon_validate falls back to GPT-4o on L2/L3.
ANTHROPIC_KEY = ""
_anthropic_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anthropic_key.txt")
if os.path.exists(_anthropic_key_file):
    ANTHROPIC_KEY = open(_anthropic_key_file, "r").read().strip()
if not ANTHROPIC_KEY:
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FALCON_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# L4 clinical reconstruction uses Anthropic Sonnet 4.6 with extended thinking.
# Reasoning trace is the validator — Falcon is skipped at L4 (the model
# self-checks during the thinking phase). Fallback to GPT-4o if Anthropic
# unavailable. Thinking budget 8000 tokens; max output 16000 (must exceed budget).
SONNET_THINK_MODEL = "claude-sonnet-4-6"
SONNET_THINK_BUDGET = 8000
SONNET_THINK_MAX_TOKENS = 16000

_last_recon_model = ""  # updated by reconstruct() — shows in log status line

LANGUAGE = "en"
PREFERRED_MIC = "C930"
RECORD_KEY = "f9"
TONE_KEY = "f10"
LAYER_KEY = "f11"
STATS_KEY = "f12"
QUIT_KEY = "f3"
COMMAND_KEY = "f8"  # Command Mode: highlight text + say command → transforms selection
MODEL = "gpt-4o"                     # L2/L3 reconstruction — full GPT-4o (most accurate)
MODEL_L4 = "gpt-4o"                  # L4 stutter reconstruction (same model, different prompt)
WHISPER_TEMP = 0.0                   # Whisper decoder temperature (0.0=deterministic, 1.0=creative)
WHISPER_NO_SPEECH_THRESHOLD = 0.15   # Post-hoc filter: segments with no_speech_prob > this are flagged as block suspects
                                     # OpenAI API doesn't expose no_speech_threshold — we filter client-side
                                     # using verbose_json no_speech_prob. Lower = preserve more blocks.
WHISPER_MULTI_TEMP = False           # Multi-temperature voting: OFF by default (3x cost, avg_logprob catches same artifacts)
WHISPER_MULTI_TEMPS = [0.0, 0.2, 0.4]  # Temperature schedule for voting passes
# Patience mode — extended silence threshold for PWS (Apple ML Research, 2023)
# Default endpointer cuts off PWS 23.8% of the time. Extending to 4.5s reduces to <3%.
PATIENCE_DEFAULT = 2.0   # seconds — normal silence threshold
PATIENCE_STUTTER = 4.5   # seconds — Layer 4 / High Stress
LOCAL_WHISPER = True                 # L1 ASR runs locally (no cloud fallback at L1 — local layers stay local).
LOCAL_WHISPER_MODEL_SIZE = "base"    # Moonshine fallback size (kept for the secondary fallback path)
LOCAL_FW_MODEL_SIZE = os.environ.get("LAV_FW_MODEL_SIZE", "large-v3-turbo")  # faster-whisper primary (real Whisper, full verbose JSON)
LOCAL_FW_COMPUTE_TYPE = os.environ.get("LAV_FW_COMPUTE_TYPE", "int8")         # CPU-friendly quantization
LOCAL_FW_DEVICE = os.environ.get("LAV_FW_DEVICE", "cpu")                       # target eval hardware
LOCAL_LLM_MODEL = os.environ.get("LAV_LOCAL_LLM", "llama3.2:3b-instruct-q4_K_M")  # L2/L3 brain
# Layered local ASR: faster-whisper (primary) -> Moonshine (secondary) -> Vosk
# (tertiary) -> raise. Composite dispatcher in local/asr_local.py exposes the
# same `transcribe` signature so call sites below don't change. If the composite
# module can't import, fall back to Moonshine alone so legacy installs keep working.
try:
    from local.asr_local import transcribe as _local_transcribe_fn  # noqa: F401
except ImportError:
    try:
        from local.whisper_local import transcribe as _local_transcribe_fn  # noqa: F401
    except ImportError:
        _local_transcribe_fn = None

# Local LLM for L2/L3 reconstruction (Gemma via Ollama). L4 stays on cloud
# GPT-4o. If the local LLM isn't available or returns None, L2/L3 fall
# back to the pre-cleaned raw text (strip_disfluencies + profile corrections)
# rather than the cloud — per the "local layers stay local" principle.
try:
    from local.llm_local import complete as _local_llm_complete  # noqa: F401
    from local.llm_local import is_available as _local_llm_available  # noqa: F401
except ImportError:
    _local_llm_complete = None
    _local_llm_available = lambda: False  # noqa: E731

LAVRENTIY_DIR = Path.home() / ".lavrentiy"
PROFILES_ROOT = LAVRENTIY_DIR / "profiles"
ACTIVE_FILE = LAVRENTIY_DIR / "active_profile"
DEFAULT_PROFILE_NAME = "Default"
DASHBOARD_PORT = 7878

def _read_active_profile_name():
    """Always boot to Default. The disk active_profile file is intentionally
    ignored on cold start so the "last user on this machine" doesn't persist
    as the implicit signed-in identity across restarts. Sign-in via /api/auth
    swaps the runtime profile to the email-matched one for the session;
    sign-out swaps back to Default; engine shutdown rewrites the file to
    Default (atexit + F3-x-3 paths) so even the disk state stays clean.
    """
    return DEFAULT_PROFILE_NAME

def _write_active_profile_name(name):
    LAVRENTIY_DIR.mkdir(exist_ok=True)
    ACTIVE_FILE.write_text(name, encoding='utf-8')

# Reset active_profile to Default at engine shutdown so a cold restart
# never inherits "last person who used this machine" as the implicit
# signed-in user. Catches non-F3-quit exits (window close, signal, etc.).
# F3-x-3 path also calls _write_active_profile_name(DEFAULT_PROFILE_NAME)
# explicitly before os._exit(0) for the same reason.
try:
    import atexit as _atexit_profile
    @_atexit_profile.register
    def _reset_active_profile_at_exit():
        try:
            _write_active_profile_name(DEFAULT_PROFILE_NAME)
        except Exception:
            pass
except Exception:
    pass

def _resolve_profile_paths(name):
    """Return (PROFILE_DIR, PROFILE_PATH, DB_PATH, BACKUP_DIR) for a given profile name."""
    pdir = PROFILES_ROOT / name
    return pdir, pdir / "profile.json", pdir / "history.db", pdir / "backups"

_active_profile_name = _read_active_profile_name()
PROFILE_DIR, PROFILE_PATH, DB_PATH, BACKUP_DIR = _resolve_profile_paths(_active_profile_name)
DASHBOARD_PATH = LAVRENTIY_DIR / "dashboard.html"

# -- Phase 2 config ──────────────────────────────────────────────
MODE = "SAFE"                     # RAW | FAST | SAFE (default)
MODES = ["RAW", "FAST", "SAFE"]
LEARN_PROMOTION_THRESHOLD = 2     # candidate recurrences before promotion
MAX_PROFILE_ITEMS = 200           # cap per profile section
HOLD_ON_HIGH_RISK = False         # True = skip paste when risk_flags present
PROFILE_VERSION = 4

# -- One-time migration: flat layout → profiles/<Default>/ ──────
if not PROFILES_ROOT.exists():
    _old_profile = LAVRENTIY_DIR / "profile.json"
    _old_db = LAVRENTIY_DIR / "history.db"
    _old_backups = LAVRENTIY_DIR / "backups"
    if _old_profile.exists() or _old_db.exists():
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        if _old_profile.exists():
            shutil.move(str(_old_profile), str(PROFILE_PATH))
        if _old_db.exists():
            shutil.move(str(_old_db), str(DB_PATH))
        if _old_backups.exists():
            shutil.move(str(_old_backups), str(BACKUP_DIR))
        _write_active_profile_name(DEFAULT_PROFILE_NAME)
        try:
            print(f"Migrated profile to profiles/{DEFAULT_PROFILE_NAME}/")
        except Exception:
            pass

# -- Live preview config ─────────────────────────────────────────
LIVE_PREVIEW_ENABLED = False      # True = stream interim transcripts
PREVIEW_PROVIDER = "none"         # none | deepgram | assemblyai | google
PREVIEW_LANGUAGE = "en"

# -- DAF (Delayed Auditory Feedback) ─────────────────────────────
DAF_DEFAULT_DELAY_MS = 100        # default delay in milliseconds
DAF_MIN_DELAY_MS = 30
DAF_MAX_DELAY_MS = 300

# -- Session audio archive (training data for future local Whisper) ──
ARCHIVE_AUDIO = True              # save session WAVs for fine-tuning
ARCHIVE_DIR = PROFILE_DIR / "audio_archive"
ARCHIVE_MAX_MB = 2000             # auto-pause archiving above this (≈2GB)

# -- Calibration mode (Tier 2: structured data collection) ───────
CALIBRATION_DIR = PROFILE_DIR / "calibration"
CALIBRATION_PROMPTS = [
    # Category 1: Smart Home / Virtual Assistant (short commands)
    {"id": 1,  "category": "smart_home", "text": "Turn off the kitchen lights"},
    {"id": 2,  "category": "smart_home", "text": "Set the thermostat to seventy-two degrees"},
    {"id": 3,  "category": "smart_home", "text": "Lock the front door"},
    {"id": 4,  "category": "smart_home", "text": "Play my morning playlist on the living room speaker"},
    {"id": 5,  "category": "smart_home", "text": "Set a timer for fifteen minutes"},
    # Category 2: Healthcare (medium complexity, clinical terms)
    {"id": 6,  "category": "healthcare", "text": "Schedule an appointment with Doctor Peterson for next Thursday"},
    {"id": 7,  "category": "healthcare", "text": "Refill my prescription for blood pressure medication"},
    {"id": 8,  "category": "healthcare", "text": "I need to cancel my physical therapy session on Friday"},
    {"id": 9,  "category": "healthcare", "text": "What are the side effects of this medication"},
    {"id": 10, "category": "healthcare", "text": "Check if my insurance covers the procedure"},
    # Category 3: Finance (numbers, proper nouns)
    {"id": 11, "category": "finance", "text": "Transfer three hundred dollars to my savings account"},
    {"id": 12, "category": "finance", "text": "What is my current credit card balance"},
    {"id": 13, "category": "finance", "text": "Pay the electricity bill before the fifteenth"},
    {"id": 14, "category": "finance", "text": "Show me transactions from the past two weeks"},
    {"id": 15, "category": "finance", "text": "Set up automatic payment for my student loan"},
    # Category 4: Navigation / Travel (place names, directions)
    {"id": 16, "category": "navigation", "text": "Navigate to the nearest gas station"},
    {"id": 17, "category": "navigation", "text": "What time does the train to San Francisco depart"},
    {"id": 18, "category": "navigation", "text": "Find a restaurant within walking distance"},
    {"id": 19, "category": "navigation", "text": "Book a hotel room for two nights starting Saturday"},
    {"id": 20, "category": "navigation", "text": "How long is the drive to the airport from here"},
    # Category 5: Communication (emails, calls, messages)
    {"id": 21, "category": "communication", "text": "Send a message to Jana saying I will be home by six"},
    {"id": 22, "category": "communication", "text": "Read my most recent email from work"},
    {"id": 23, "category": "communication", "text": "Call the dentist office and ask about availability"},
    {"id": 24, "category": "communication", "text": "Reply to the last message and say sounds good"},
    {"id": 25, "category": "communication", "text": "Compose an email to my manager about the project deadline"},
    # Category 6: Shopping / E-commerce
    {"id": 26, "category": "shopping", "text": "Add milk and eggs to my grocery list"},
    {"id": 27, "category": "shopping", "text": "Order the blue jacket in size medium"},
    {"id": 28, "category": "shopping", "text": "Compare prices for wireless headphones"},
    {"id": 29, "category": "shopping", "text": "Return the package I received yesterday"},
    {"id": 30, "category": "shopping", "text": "Track the delivery status of my recent order"},
    # Category 7: Work / Productivity (longer, more complex)
    {"id": 31, "category": "productivity", "text": "Create a meeting for Tuesday at two o'clock with the design team"},
    {"id": 32, "category": "productivity", "text": "Remind me to submit the quarterly report by end of day Friday"},
    {"id": 33, "category": "productivity", "text": "Move my three o'clock meeting to four thirty"},
    {"id": 34, "category": "productivity", "text": "Take a note that the client wants the proposal revised by Monday"},
    {"id": 35, "category": "productivity", "text": "What is on my calendar for tomorrow morning"},
    # Category 8: Media / Entertainment
    {"id": 36, "category": "media", "text": "Play the latest episode of my podcast"},
    {"id": 37, "category": "media", "text": "Turn on closed captioning for this video"},
    {"id": 38, "category": "media", "text": "Search for comedy movies released this year"},
    {"id": 39, "category": "media", "text": "Pause the music and set a sleep timer for thirty minutes"},
    {"id": 40, "category": "media", "text": "Show me the news headlines from today"},
    # Category 9: Phonetically challenging (loaded with known trigger onsets)
    {"id": 41, "category": "phonetic_challenge", "text": "Please print the presentation before the conference call"},
    {"id": 42, "category": "phonetic_challenge", "text": "The critical component of the contract requires clarification"},
    {"id": 43, "category": "phonetic_challenge", "text": "Can you confirm the customer complaint was properly documented"},
    {"id": 44, "category": "phonetic_challenge", "text": "The committee concluded that the proposal needs comprehensive revisions"},
    {"id": 45, "category": "phonetic_challenge", "text": "Prepare the quarterly performance report for the board presentation"},
    # Category 10: Spontaneous / Conversational (longer, natural speech)
    {"id": 46, "category": "spontaneous", "text": "Tell me about a time you had to work under pressure to meet a deadline"},
    {"id": 47, "category": "spontaneous", "text": "Describe a project you are most proud of and explain why"},
    {"id": 48, "category": "spontaneous", "text": "What would you do if you disagreed with a decision your manager made"},
    {"id": 49, "category": "spontaneous", "text": "Explain how you would handle a situation where a coworker is not contributing to a group project"},
    {"id": 50, "category": "spontaneous", "text": "If you could improve one thing about your daily routine what would it be and why"},
    # Category 11: Technical / Bilingual (code-switching, technical terms)
    {"id": 51, "category": "technical", "text": "Deploy the latest build to the staging environment"},
    {"id": 52, "category": "technical", "text": "The database connection timed out during the migration"},
    {"id": 53, "category": "technical", "text": "Run the automated test suite and send me the results"},
    {"id": 54, "category": "technical", "text": "Check if the pull request has any merge conflicts"},
    {"id": 55, "category": "technical", "text": "The API endpoint is returning a five hundred internal server error"},
    # Category 12: Personal / Emotional (names, family, feelings)
    {"id": 56, "category": "personal", "text": "Remind me to pick up Alex from school at three fifteen"},
    {"id": 57, "category": "personal", "text": "Add dog food and treats to the shopping list"},
    {"id": 58, "category": "personal", "text": "Call my wife and tell her I am running about twenty minutes late"},
    {"id": 59, "category": "personal", "text": "Save this recipe for banana bread so I can make it this weekend"},
    {"id": 60, "category": "personal", "text": "Set an alarm for six thirty tomorrow morning"},
]

# -- Stutter insights ────────────────────────────────────────────
STUTTER_TIPS = {
    "trigger_cluster": {
        "title": "Recurring trigger words detected",
        "body": (
            "You are repeatedly blocking on a small set of words. "
            "Technique — Preparatory Set: before approaching a known trigger word, "
            "pause briefly, relax your articulators, and mentally rehearse a smooth, "
            "light contact on the first sound. "
            "Technique — Voluntary Stuttering: practice easy, deliberate bounces on "
            "these trigger words in low-pressure settings to drain anticipatory fear. "
            "Most triggers start with stop plosives (/p/, /b/, /t/, /d/, /k/, /g/) or "
            "consonant clusters — focus coarticulation practice on blending through "
            "the first two sounds of each trigger word."
        ),
        "source": "Stuttering Foundation — Book0016.pdf, stromsta_book.pdf",
    },
    "high_filler_load": {
        "title": "Heavy filler use — postponement pattern",
        "body": (
            "Your speech is using filler words (um, uh, well, you know) as starters — "
            "delay tactics to jump-start vocal cords before a feared word. This is a "
            "covert avoidance behavior. "
            "Technique — Easy Onset: instead of inserting a filler, initiate the feared "
            "sound gently with minimal muscle tension and continuous airflow. Touch the "
            "articulators together very lightly without letting pressure build. "
            "Practice replacing each filler with a brief, deliberate silent pause — "
            "silence is more fluent than a filler chain."
        ),
        "source": "Stuttering Foundation — PedBook.pdf, teacher_book_2010.pdf",
    },
    "correction_pattern": {
        "title": "Repeated misrecognitions — coarticulation targets",
        "body": (
            "The same words are being misheard repeatedly by speech-to-text. "
            "This often indicates these words have disfluency residue (prolongations, "
            "schwa insertions, or incomplete consonant-vowel transitions) that confuses "
            "the ASR model. "
            "Technique — Coarticulation Practice: for each misrecognized word, mentally "
            "prepare for the second sound, then produce the first sound as a strong, "
            "deliberate physical movement into and through that second sound. "
            "Add these words to your preferred vocabulary so the engine learns them."
        ),
        "source": "Stuttering Foundation — stromsta_book.pdf",
    },
    "fast_growth_triggers": {
        "title": "New triggers emerging — context shift detected",
        "body": (
            "New trigger words are appearing quickly. This typically signals a change in "
            "speaking context — increased time pressure, authority figures, unfamiliar "
            "vocabulary, or telephone use. The vicious cycle: anxiety about blocking "
            "creates physical tension that locks the vocal mechanism, causing more blocks. "
            "Technique — Pull-Out: when you feel a block starting mid-word, don't force "
            "through it. Hold the tension deliberately, slow it down to gain voluntary "
            "control, then ease out smoothly into the vowel. "
            "Watch for approach-avoidance conflict: the urge to avoid speaking can "
            "overtake the desire to communicate."
        ),
        "source": "Stuttering Foundation — Book0016.pdf, 0031.pdf",
    },
    "dominant_onset_pattern": {
        "title": "Personal phonetic pattern detected",
        "body": (
            "Your blocks are clustering on a specific set of initial sounds. "
            "This is the core of your stutter fingerprint — not random, but phonetically "
            "systematic. Lavrentiy has learned which onsets you personally struggle with "
            "and is now weighting predictions accordingly. "
            "Technique — Targeted Coarticulation: for your dominant onset sounds, practice "
            "blending the first two sounds together as one smooth movement. Don't 'hit' "
            "the first consonant — glide through it into the vowel. "
            "Technique — Preparatory Set: before words starting with your high-risk sounds, "
            "position your articulators gently and start airflow before voicing."
        ),
        "source": "Ghai & Mueller (ASSETS '21) — phonetic pattern learning; Stuttering Foundation",
    },
    "stable_profile": {
        "title": "Stable fluency pattern",
        "body": (
            "Your recent sessions show stable patterns with no emerging concerns. "
            "Keep using the speaking rhythm that works. Remember: stutterers actually "
            "stutter in only 5-25% of speech — 75-95% falls within normal fluency. "
            "Fluency enhancers to maintain: low-stress contexts, continuous airflow, "
            "and light articulatory contacts. If you feel a block approaching, use a "
            "Preparatory Set — pause, relax, and pre-form a gentle posture for the "
            "first sound."
        ),
        "source": "Stuttering Foundation — PedBook.pdf, Book0016.pdf",
    },
}
MAX_INSIGHTS = 6

TONES = ["casual", "professional", "friend", "formal"]
TONE_SHORT = {"casual": "CAS", "professional": "PRO", "friend": "FRD", "formal": "FRM"}
LAYERS = [1, 2, 3, 4]
LAYER_NAMES = {1: "transcribe", 2: "reconstruct", 3: "profile", 4: "stutter"}

# -- Situational context (affects reconstruction aggressiveness) ──
SITUATIONS = ["default", "high_stress", "reading"]
SITUATION_SEVERITY = {
    "default":      1.0,
    "high_stress":  1.5,   # phone, presentation, interview — max assist
    "reading":      0.3,   # reading aloud = near-fluent for most PWS
}
# Back-compat: old situation names map to new ones
_SITUATION_ALIASES = {
    "phone": "high_stress", "presentation": "high_stress",
    "interview": "high_stress", "casual": "default",
}
current_situation = "default"

# -- Phonetic trigger prediction ──────────────────────────────────
# Stop plosives, affricates, and clusters that cause >90% of blocks
# Source: Category 1 — initial sounds, unvoiced consonants, content words
HIGH_RISK_ONSETS = {
    # Unvoiced stop plosives (highest risk)
    'p', 't', 'k',
    # Voiced stop plosives
    'b', 'd', 'g',
    # Spelling variant: 'c' maps to /k/ (cat, come, call) or /s/ (city, cell)
    # Both are risky — /k/ is a plosive, /s/ is a fricative. Adding 'c' catches
    # words like "computer", "conference", "could" that _extract_onset missed.
    'c',
    # Affricates
    'ch', 'j',
    # High-risk consonant clusters
    'bl', 'br', 'cl', 'cr', 'dr', 'fl', 'fr', 'gl', 'gr',
    'pl', 'pr', 'sc', 'sk', 'sl', 'sm', 'sn', 'sp', 'st',
    'str', 'sw', 'tr', 'tw', 'thr', 'shr', 'scr', 'spl', 'spr',
}

# Russian high-risk onsets (#13: per-language trigger profiles)
# Palatalized consonants + clusters that cause blocks in Russian speech.
# Russian stuttering has different phonetic triggers than English:
# - Palatalized stops /т'/, /д'/, /к'/ are harder than their hard counterparts
# - Clusters like /стр/, /пр/, /кр/ mirror English cluster difficulty
# - Russian-specific: /щ/ (long palatalized fricative), /ц/ (affricate)
HIGH_RISK_ONSETS_RU = {
    # Hard stop consonants
    'п', 'т', 'к', 'б', 'д', 'г',
    # Palatalized stops (soft — written with ь or before е/и/ё/ю/я)
    'пь', 'ть', 'кь', 'бь', 'дь', 'гь',
    # Affricates
    'ц', 'ч',
    # Fricatives (high effort)
    'щ', 'ш', 'ж',
    # Clusters (same difficulty pattern as English)
    'пр', 'тр', 'кр', 'бр', 'др', 'гр',
    'пл', 'кл', 'бл', 'гл', 'сл', 'сн',
    'ст', 'стр', 'скр', 'спр', 'скл',
    'вс', 'вз', 'зд', 'зн',
}

# Combined lookup for any-language onset extraction
HIGH_RISK_ONSETS_ALL = HIGH_RISK_ONSETS | HIGH_RISK_ONSETS_RU


# ─── Multilingual L4 helpers (docs/l4_prompt_engineering_memo.md) ───
# Lang packs live in lang_packs/{code}.json; mirrored into the wim-android
# APK under app/src/main/assets/lang_packs/. The two sets MUST stay in sync.
_LANG_PACK_CACHE = {}  # code -> dict or None (None = not found)


def _lang_packs_dir():
    # Lazy: resolve only when needed so exec-based test harnesses that lack
    # __file__ (e.g. test_fuzz.py) don't fail at import time.
    return Path(__file__).resolve().parent / "lang_packs"


def _load_lang_pack(code):
    """Return the parsed lang-pack dict for `code`, or None for English/unknown."""
    normalized = _normalize_lang_code(code)
    if normalized in _LANG_PACK_CACHE:
        return _LANG_PACK_CACHE[normalized]
    if normalized == "en":
        _LANG_PACK_CACHE[normalized] = None
        return None
    try:
        path = _lang_packs_dir() / f"{normalized}.json"
        if not path.exists():
            _LANG_PACK_CACHE[normalized] = None
            return None
        with open(path, "r", encoding="utf-8") as f:
            pack = json.load(f)
    except Exception:
        pack = None
    _LANG_PACK_CACHE[normalized] = pack
    return pack


def _normalize_lang_code(raw):
    """Collapse 'en-US' → 'en', 'es-ES' → 'es'. Empty/None → 'en'."""
    if not raw:
        return "en"
    head = raw.strip().split("-", 1)[0].split("_", 1)[0].lower()
    return head or "en"


def _lang_name(code):
    normalized = _normalize_lang_code(code)
    if normalized == "en":
        return "English"
    pack = _load_lang_pack(normalized)
    return (pack or {}).get("language_name_en", normalized) or normalized


def _get_lang_fillers(code):
    pack = _load_lang_pack(code)
    return list((pack or {}).get("fillers", []))


def _get_lang_natural_repeats(code):
    pack = _load_lang_pack(code)
    return list((pack or {}).get("natural_repeats", []))


def _get_lang_hard_onsets(code):
    """Cited onset→weight map from lang pack. Empty when unavailable."""
    pack = _load_lang_pack(code)
    if not pack:
        return {}
    ho = pack.get("hard_onsets") or {}
    if ho.get("quality_note") == "unavailable":
        return {}
    out = {}
    for entry in ho.get("data") or []:
        onset = (entry.get("onset") or "").strip().strip("/").lower()
        weight = entry.get("difficulty_weight") or 0.0
        if onset and weight:
            out[onset] = weight
    return out


def _lang_has_no_onset_research(code):
    normalized = _normalize_lang_code(code)
    if normalized == "en":
        return False
    pack = _load_lang_pack(normalized)
    if not pack:
        return False
    return (pack.get("hard_onsets") or {}).get("quality_note") == "unavailable"


def _get_lang_part_word_example(code):
    c = _normalize_lang_code(code)
    return {
        "es": "'p-p-pues entonces qu-qu-quiero ir al trabajo' → 'Pues, quiero ir al trabajo'",
        "fr": "'P-p-peut-être qu'on devrait...' → 'Peut-être qu'on devrait...'",
        "de": "'P-p-Peter hat mir gesagt...' → 'Peter hat mir gesagt...'",
        "it": "'P-p-posso andare a-a-adesso?' → 'Posso andare adesso?'",
        "pt": "'P-p-posso te falar a-a-agora?' → 'Posso te falar agora?'",
        "ja": "'か-か-かく に つ い て は...' → 'かくについては...' (mora-level repetition)",
        "zh": "'我-我-我 想 去' → '我想去'",
        "hi": "'म-म-मैं जाना चाहता हूँ' → 'मैं जाना चाहता हूँ'",
        "ar": "'ب-ب-بدي أروح' → 'بدي أروح'",
        "ko": "'ㄱ-ㄱ-가고 싶어요' → '가고 싶어요'",
    }.get(c, "'b-b-b-buy' → 'buy', 'Ca-ca-ca-can' → 'Can'")


def _get_lang_prolongation_example(code):
    c = _normalize_lang_code(code)
    return {
        "es": "'Sssssseñor, necesito...' → 'Señor, necesito...'",
        "fr": "'Ssssalut, je voulais...' → 'Salut, je voulais...'",
        "de": "'Mmmmontag kommt er zurück' → 'Montag kommt er zurück'",
        "it": "'Mmmmmamma mia' → 'Mamma mia'",
        "pt": "'Sssssenhor, preciso...' → 'Senhor, preciso...'",
        "ja": "prolonged initial mora: 'かーーーく' → 'かく'",
    }.get(c, "'mmmmaybe' → 'maybe', 'Sssssscience' → 'Science'")


def _get_lang_epenthesis_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "Spanish epenthetic /e/ during blocked clusters (e.g. 'p-eh-lanta' for 'planta', 't-eh-rabajo' for 'trabajo') — NOT English schwa /ə/",
        "fr": "French epenthetic /ə/ during blocked clusters, but this is the French 'e muet', not the neutral English schwa",
        "de": "German epenthetic /ə/ possible at morpheme boundaries in compounds",
        "it": "Italian may insert a transitional /i/ or /e/ at blocked clusters",
        "pt": "Portuguese may insert a transitional /i/ (BP) or /ə/ (EP) at blocked clusters",
        "hi": "Hindi: inherent /a/ vowel of Devanagari consonants can be extended during blocks",
    }.get(c, "schwa substitution: 'guh-guh-goat' → 'goat' (neutral /ə/ inserted in repeated clusters)")


def _get_lang_dialect_avoidance_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "- Spanish dialect avoidance: if speaker uses 'vos tenés' but context suggests 'tú tienes', they may be using voseo to avoid the /t/ onset. Do NOT reconstruct voseo into tuteo — preserve the speaker's dialect.",
        "fr": "- French tu/vous register: an unexpected vous-form when tu is established may be avoidance of a /t/ onset. Do NOT reconstruct vous into tu.",
        "de": "- German du/Sie register: an unexpected Sie-form when du is established MAY indicate avoidance of a /d/ onset (speculative — not established in German stuttering literature). Preserve the speaker's chosen form.",
        "ja": "- Japanese casual/keigo register: an unexpected keigo form on a content word MAY indicate avoidance of a feared initial consonant (speculative — not established in Japanese stuttering literature). Preserve the speaker's chosen form.",
        "ko": "- Korean 반말/존댓말 register: an unexpected register shift MAY indicate phonemic avoidance (speculative — not established in Korean stuttering literature). Preserve the speaker's chosen form.",
        "ar": "- Arabic diglossia: an unexpected colloquial→MSA (عامية→فصحى) shift on a specific word MAY indicate register avoidance (speculative — not established in Arabic stuttering literature). Preserve the speaker's chosen register.",
    }.get(c, "")


def _get_lang_syllable_timing_note(code):
    c = _normalize_lang_code(code)
    if c in ("es", "fr", "it", "pt"):
        return f"- {_lang_name(c)} is syllable-timed — anticipatory pauses are less prosodically marked than in English. Require both a filler cluster AND a hard-onset match before treating a pause as anticipatory."
    if c == "de":
        return "- German is stress-timed — anticipatory pauses have predictive weight similar to English."
    if c == "ja":
        return "- Japanese is mora-timed — stuttering occurs at mora boundaries, not English-style word-initial position."
    return ""


def _get_lang_epenthesis_corruption_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "EPENTHETIC VOWEL CORRUPTION: blocked clusters (/tr/, /pl/, /pr/) → Whisper may transcribe 'p-eh-lanta' as 'Pelanta', 't-eh-rabajo' as 'Terabajo' — these are hallucinations of epenthesis, reconstruct to the target word",
        "fr": "LIAISON HALLUCINATION: Whisper may insert liaison consonants mid-block (e.g. transcribing a /t/ the speaker was blocked on as the onset of the next vowel-initial word)",
        "de": "COMPOUND BOUNDARY CORRUPTION: blocks at morpheme boundaries of long compounds (e.g. 'Arbeits…losigkeit') may be transcribed as two separate words or as a different compound",
        "it": "GEMINATE CONFUSION: stuttered /p/ may be transcribed as the Italian geminate /pp/ ('la papa' vs. 'la pappa') — geminates are phonemic, verify against context",
        "pt": "EPENTHETIC /i/ CORRUPTION: blocked clusters in BP may be transcribed with an intrusive /i/ (e.g. 'p-i-lanta' for 'planta')",
        "ja": "MORA CORRUPTION: repeated moras ('か-か-かく') may collapse into a single mora or a different katakana/hiragana character",
        "zh": "TONE CORRUPTION: repeated syllables in Mandarin may be transcribed with a wrong tone, producing a different word (same pinyin, different character)",
    }.get(c, "SCHWA CORRUPTION: neutral vowel in repeated clusters → transcribed as a real word (e.g. 'buh-buh-blue' → 'but but blue' or 'above blue')")


def _get_lang_onset_caveat(code):
    c = _normalize_lang_code(code)
    return {
        "es": "Onset weights cite Howell et al. 2004 and are extrapolated from English aspiration data — may be slightly inflated for Spanish unaspirated plosives. Additionally, the trilled /rr/ (perro, ratón) is a high-frequency block site not captured in these weights.",
        "fr": "Onset weights cite Dworzynski et al. 2003. French is unaspirated — treat with moderate extrapolation risk relative to English.",
        "de": "Onset weights cite Natke et al. 2004. Only /p/ is documented as a primary hard onset in German — do NOT apply English-derived /t/ difficulty weighting.",
        "it": "Onset weights cite Zmarich et al. 2004. Italian is unaspirated — moderate extrapolation risk.",
        "pt": "Onset weights cite Juste et al. 2007, a pediatric study — adult onset weights are extrapolated; treat with lower confidence for adult users.",
        "ja": "Onset weights cite Umezaki et al. 1999. /k/ is the documented hard onset; words beginning with か行 (ka, ki, ku, ke, ko) are elevated-risk.",
    }.get(c, "")


# Few-shot example blocks per language (memo Section 4.4).
_LANG_FEW_SHOT = {
    "es": (
        "DISFLUENCY EXAMPLES (Spanish):\n"
        "  REPETITION:  'P-p-pues este... quiero ir a la re-re-reunión'\n"
        "  RESULT:      'Quiero ir a la reunión'\n\n"
        "  EMPHATIC (PRESERVE):  'No no, eso no me parece bien'\n"
        "  RESULT:      'No no, eso no me parece bien'\n\n"
        "  WHISPER /rr/ BLOCK:  'Necesito el r-r-... el documento del er rrr... del jefe'\n"
        "  RESULT:      'Necesito el documento del jefe'\n\n"
        "  CIRCUMLOCUTION:  'Quiero hablar con el... con la persona que lleva los números'\n"
        "  RESULT:      'Quiero hablar con el contador'  [if context is clear — else preserve circumlocution literally]"
    ),
    "fr": (
        "DISFLUENCY EXAMPLES (French):\n"
        "  REPETITION:  'Je je je voulais te te te dire quelque chose'\n"
        "  RESULT:      'Je voulais te dire quelque chose'\n\n"
        "  EMPHATIC (PRESERVE):  'Non non, ce n'est pas correct'\n"
        "  RESULT:      'Non non, ce n'est pas correct'\n\n"
        "  BLOCK + LIAISON:  'Les... euh... [block]... petits enfants arrivent'\n"
        "  RESULT:      'Les petits enfants arrivent'\n\n"
        "  CIRCUMLOCUTION:  'J'ai besoin du... de la chose qu'on met sur la tête'\n"
        "  RESULT:      'J'ai besoin du chapeau'  [if context is clear]"
    ),
    "de": (
        "DISFLUENCY EXAMPLES (German):\n"
        "  REPETITION:  'P-p-Peter, ich brauche den Ber-ber-Bericht bis Freitag'\n"
        "  RESULT:      'Peter, ich brauche den Bericht bis Freitag'\n\n"
        "  EMPHATIC (PRESERVE):  'Nein nein, das ist nicht richtig'\n"
        "  RESULT:      'Nein nein, das ist nicht richtig'\n\n"
        "  COMPOUND BLOCK:  'Ich brauche die Ar-ar-Arbeits... die Bescheinigung'\n"
        "  RESULT:      'Ich brauche die Arbeitsbescheinigung'\n\n"
        "  WHISPER HALLUCINATION:  'Ich dachte dass... thank you... der Termin morgen ist'\n"
        "  RESULT:      'Ich dachte, der Termin ist morgen'  [discard 'thank you' — Whisper hallucination]"
    ),
    "it": (
        "DISFLUENCY EXAMPLES (Italian):\n"
        "  REPETITION:  'P-p-posso andare a-a-adesso?'\n"
        "  RESULT:      'Posso andare adesso?'\n\n"
        "  EMPHATIC (PRESERVE):  'Sì sì, è proprio così'\n"
        "  RESULT:      'Sì sì, è proprio così'\n\n"
        "  GEMINATE DISAMBIGUATION:  'La p-p-papa parla' (stuttered /p/)\n"
        "  RESULT:      'Il papa parla'  [stuttered /p/, NOT the geminate 'pappa' (porridge)]\n\n"
        "  CIRCUMLOCUTION:  'Ho bisogno del... di quella cosa per scrivere'\n"
        "  RESULT:      'Ho bisogno della penna'  [if context is clear]"
    ),
    "pt": (
        "DISFLUENCY EXAMPLES (Portuguese):\n"
        "  REPETITION:  'P-p-posso te falar a-a-agora sobre o pro-projeto?'\n"
        "  RESULT:      'Posso te falar agora sobre o projeto?'\n\n"
        "  EMPHATIC (PRESERVE):  'Não não, isso não está certo'\n"
        "  RESULT:      'Não não, isso não está certo'\n\n"
        "  DIALECT PRESERVATION:  'Vou pegar o ônibus' (BP) — do NOT normalize to 'autocarro' (EP)\n"
        "  RESULT:      'Vou pegar o ônibus'\n\n"
        "  CIRCUMLOCUTION:  'Preciso do... daquilo que a gente assina na entrada'\n"
        "  RESULT:      'Preciso do formulário da entrada'"
    ),
    "ja": (
        "DISFLUENCY EXAMPLES (Japanese):\n"
        "  MORA REPETITION:  'か-か-かく に つ い て は...'\n"
        "  RESULT:      'かくについては...'\n\n"
        "  EMPHATIC (PRESERVE):  'そうそう、それが正しいです'\n"
        "  RESULT:      'そうそう、それが正しいです'\n\n"
        "  /k/ BLOCK:  'きょう の... えーと... かいぎ は なんじ ですか'\n"
        "  RESULT:      'きょうのかいぎはなんじですか'"
    ),
    "zh": (
        "DISFLUENCY EXAMPLES (Mandarin):\n"
        "  REPETITION:  '我-我-我 想 去 开-开-开会'\n"
        "  RESULT:      '我想去开会'\n\n"
        "  EMPHATIC (PRESERVE):  '对对，这个就是正确的'\n"
        "  RESULT:      '对对，这个就是正确的'\n\n"
        "  ASPECTUAL REDUPLICATION (PRESERVE):  '我去看看' (take a look — NOT stutter)\n"
        "  RESULT:      '我去看看'\n\n"
        "  TONE-LEVEL SUBSTITUTION RISK: suspect single-syllable content-word substitutions"
    ),
    "hi": (
        "DISFLUENCY EXAMPLES (Hindi):\n"
        "  REPETITION:  'म-म-मैं जाना चाहता हूँ'\n"
        "  RESULT:      'मैं जाना चाहता हूँ'\n\n"
        "  EMPHATIC (PRESERVE):  'नहीं नहीं, यह सही नहीं है'\n"
        "  RESULT:      'नहीं नहीं, यह सही नहीं है'\n\n"
        "  CIRCUMLOCUTION:  'मुझे वो... जो लिखने के लिए होता है... चाहिए'\n"
        "  RESULT:      'मुझे पेन चाहिए'  [if context is clear]"
    ),
    "ar": (
        "DISFLUENCY EXAMPLES (Arabic):\n"
        "  REPETITION:  'ب-ب-بدي أ-أ-أروح'\n"
        "  RESULT:      'بدي أروح'\n\n"
        "  EMPHATIC (PRESERVE):  'لا لا، هذا مش صحيح'\n"
        "  RESULT:      'لا لا، هذا مش صحيح'\n\n"
        "  WHISPER ENGLISH HALLUCINATION:  'كنت أفكر... thank you... في الموعد'\n"
        "  RESULT:      'كنت أفكر في الموعد'  [discard 'thank you' — Whisper hallucination]"
    ),
    "ko": (
        "DISFLUENCY EXAMPLES (Korean):\n"
        "  REPETITION:  '가-가-가고 싶-싶-싶어요'\n"
        "  RESULT:      '가고 싶어요'\n\n"
        "  EMPHATIC (PRESERVE):  '아니 아니, 그게 맞지 않아요'\n"
        "  RESULT:      '아니 아니, 그게 맞지 않아요'\n\n"
        "  CIRCUMLOCUTION:  '그... 쓰는 거 있잖아요... 필요해요'\n"
        "  RESULT:      '펜 필요해요'  [if context is clear]"
    ),
    "en": (
        "DISFLUENCY EXAMPLES (English):\n"
        "  BLOCK:       'I need the... [silence]... computer from the office'\n"
        "  RESULT:      'I need the computer from the office'\n\n"
        "  REPETITION:  'Ca-ca-ca-can you p-p-please send the re-report'\n"
        "  RESULT:      'Can you please send the report'\n\n"
        "  WORD REPS:   'I I I want to to to go to the the meeting'\n"
        "  RESULT:      'I want to go to the meeting'\n\n"
        "  WHISPER:     'I was trying to come put her the file'\n"
        "  RESULT:      'I was trying to get the computer file'"
    ),
}


def _get_lang_few_shot_examples(code):
    return _LANG_FEW_SHOT.get(_normalize_lang_code(code), _LANG_FEW_SHOT["en"])


def detect_word_language(word):
    """Detect language of a single word by character analysis.
    Returns 'ru' for Cyrillic, 'en' for Latin, 'unknown' for other."""
    if not word:
        return 'unknown'
    cyrillic = sum(1 for c in word if '\u0400' <= c <= '\u04ff')
    latin = sum(1 for c in word if 'a' <= c.lower() <= 'z')
    if cyrillic > latin:
        return 'ru'
    elif latin > 0:
        return 'en'
    return 'unknown'
# Function words rarely trigger blocks — content words do
FUNCTION_WORDS = {
    'a', 'an', 'the', 'is', 'am', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'shall', 'should', 'may', 'might', 'must', 'can', 'could',
    'i', 'me', 'my', 'you', 'your', 'he', 'she', 'it', 'we', 'they',
    'him', 'her', 'us', 'them', 'his', 'its', 'our', 'their',
    'this', 'that', 'these', 'those', 'and', 'but', 'or', 'nor',
    'for', 'yet', 'so', 'if', 'then', 'than', 'to', 'of', 'in',
    'on', 'at', 'by', 'with', 'from', 'into', 'not', 'no', 'up',
}

# -- Word frequency tiers (5th Brown feature) ────────────────────
# Low-frequency words are more likely to be stuttered (FluencyBank 2023).
# Tier 1: ~1500 high-frequency content words — LOW stutter risk boost
# Everything else: low-frequency — HIGHER stutter risk boost
# Function words already handled separately (0.1 floor).
# Based on SUBTLEX-US top content words by frequency rank.
_HIGH_FREQ_WORDS = frozenset({
    # Actions / common verbs
    'get', 'go', 'come', 'make', 'take', 'give', 'find', 'tell', 'ask', 'try',
    'use', 'work', 'call', 'need', 'want', 'seem', 'feel', 'leave', 'put', 'keep',
    'let', 'begin', 'show', 'hear', 'play', 'run', 'move', 'live', 'believe',
    'bring', 'happen', 'write', 'sit', 'stand', 'lose', 'pay', 'meet', 'include',
    'continue', 'set', 'learn', 'change', 'lead', 'understand', 'watch', 'follow',
    'stop', 'create', 'speak', 'read', 'allow', 'add', 'spend', 'grow', 'open',
    'walk', 'win', 'offer', 'remember', 'love', 'consider', 'appear', 'buy',
    'wait', 'serve', 'die', 'send', 'expect', 'build', 'stay', 'fall', 'cut',
    'reach', 'kill', 'remain', 'suggest', 'raise', 'pass', 'sell', 'require',
    'report', 'decide', 'pull', 'develop', 'thank', 'carry', 'break', 'receive',
    'agree', 'support', 'hold', 'produce', 'eat', 'cover', 'catch', 'draw',
    'choose', 'cause', 'point', 'listen', 'realize', 'place', 'pick', 'drop',
    'plan', 'notice', 'enjoy', 'matter', 'push', 'close', 'sing', 'drive',
    'start', 'help', 'turn', 'look', 'think', 'know', 'see', 'say', 'mean',
    'talk', 'fight', 'hang', 'sleep', 'wish', 'wear', 'fill', 'hit', 'act',
    # People / roles
    'man', 'woman', 'child', 'children', 'kid', 'girl', 'boy', 'baby', 'mother',
    'father', 'mom', 'dad', 'son', 'daughter', 'brother', 'sister', 'friend',
    'wife', 'husband', 'family', 'people', 'person', 'group', 'team', 'student',
    'teacher', 'doctor', 'guy', 'sir', 'lady', 'human', 'member', 'president',
    'king', 'god', 'police', 'officer', 'captain', 'soldier', 'judge', 'leader',
    'boss', 'worker', 'player', 'writer', 'baby', 'neighbor', 'master', 'couple',
    # Things / objects
    'time', 'year', 'day', 'way', 'thing', 'world', 'life', 'hand', 'part',
    'place', 'case', 'week', 'company', 'system', 'program', 'question', 'work',
    'government', 'number', 'night', 'point', 'home', 'water', 'room', 'area',
    'money', 'story', 'fact', 'month', 'lot', 'right', 'study', 'book', 'eye',
    'job', 'word', 'business', 'issue', 'side', 'kind', 'head', 'house', 'service',
    'game', 'power', 'car', 'city', 'door', 'name', 'food', 'face', 'air',
    'body', 'table', 'line', 'end', 'heart', 'war', 'idea', 'phone', 'dog',
    'school', 'state', 'country', 'problem', 'history', 'church', 'morning',
    'reason', 'class', 'street', 'road', 'law', 'land', 'music', 'paper',
    'picture', 'fire', 'window', 'bed', 'movie', 'party', 'market', 'color',
    'office', 'hour', 'minute', 'second', 'letter', 'court', 'floor', 'wall',
    'news', 'bit', 'light', 'piece', 'car', 'age', 'blood', 'type', 'town',
    'rock', 'order', 'step', 'stone', 'ground', 'form', 'tree', 'gun', 'sound',
    'horse', 'star', 'field', 'hair', 'arm', 'foot', 'ball', 'song', 'boat',
    'river', 'seat', 'box', 'page', 'fish', 'hat', 'level', 'space', 'goal',
    # Descriptors
    'good', 'new', 'first', 'last', 'long', 'great', 'little', 'own', 'other',
    'old', 'right', 'big', 'high', 'different', 'small', 'large', 'next', 'early',
    'young', 'important', 'few', 'public', 'bad', 'same', 'able', 'sure', 'real',
    'full', 'special', 'easy', 'clear', 'recent', 'strong', 'free', 'hard',
    'best', 'better', 'short', 'nice', 'cool', 'hot', 'cold', 'fast', 'slow',
    'dark', 'white', 'black', 'red', 'blue', 'green', 'dead', 'wrong', 'true',
    'whole', 'open', 'close', 'fine', 'happy', 'ready', 'serious', 'left',
    'pretty', 'beautiful', 'simple', 'poor', 'crazy', 'single', 'late', 'deep',
    'heavy', 'safe', 'common', 'possible', 'final', 'main', 'likely', 'half',
    # Time / abstract
    'today', 'tonight', 'tomorrow', 'yesterday', 'always', 'never', 'sometimes',
    'often', 'usually', 'already', 'still', 'enough', 'here', 'there', 'now',
    'again', 'away', 'almost', 'together', 'back', 'even', 'just', 'really',
    'maybe', 'quite', 'ever', 'probably', 'sure', 'actually', 'likely',
    # Russian high-frequency content words (bilingual speaker)
    'хорошо', 'время', 'дело', 'день', 'дом', 'жизнь', 'работа', 'человек',
    'люди', 'рука', 'год', 'место', 'мир', 'вода', 'город', 'земля', 'сторона',
    'деньги', 'голова', 'ребенок', 'слово', 'друг', 'дверь', 'глаз', 'лицо',
    'большой', 'маленький', 'новый', 'старый', 'хороший', 'плохой', 'другой',
    'первый', 'последний', 'нужно', 'можно', 'нельзя', 'надо', 'пойти',
    'сделать', 'сказать', 'знать', 'думать', 'видеть', 'хотеть', 'давать',
    'стоять', 'идти', 'говорить', 'смотреть', 'найти', 'понять', 'взять',
})


# -- Personalized onset weights (learned from user's trigger history) ──
# Rebuilt whenever trigger_words changes. Maps onset -> 0.0-1.0 weight.
# Empty = no personal data yet, fall back to population priors.
_personal_onset_weights = {}
_personal_dominant_onsets = []  # top 3 onsets for insight display

def _extract_onset(word):
    """Extract the matching high-risk onset from a word (longest match first).
    Handles both English and Russian onsets (#13)."""
    w = word.lower().strip()
    if not w:
        return None
    # Use combined onset set for any-language matching
    for length in (3, 2, 1):
        if length <= len(w):
            onset = w[:length]
            if onset in HIGH_RISK_ONSETS_ALL:
                return onset
    return None

_personal_onset_weights_by_lang = {"en": {}, "ru": {}}  # #13: per-language weights


def learn_onset_weights(trigger_words):
    """Analyze user's trigger words to learn which onsets they personally
    struggle with. Called when trigger_words list changes.

    Population prior: all high-risk onsets are equally dangerous (0.4).
    Personal model: onsets appearing in YOUR triggers get boosted
    proportional to their frequency. Onsets with zero personal evidence
    stay at the population floor.

    Also builds per-language breakdown (#13) — Russian palatalized consonants
    and English clusters are separate phonetic spaces.

    Example: triggers = [computer, conference, critical, create, class, break]
      onset counts: k=3, cr=1, cl=1, br=1  (total=6)
      k  -> freq 0.50 -> weight 0.65 (floor 0.4 + boost 0.25)
      cr -> freq 0.17 -> weight 0.48 (floor 0.4 + boost 0.08)
      Unseen onsets -> weight 0.3 (below population prior = deprioritized)

    Inspired by Ghai & Mueller (ASSETS '21) — phonetic pattern learning."""
    global _personal_onset_weights, _personal_dominant_onsets, _personal_onset_weights_by_lang
    if not trigger_words:
        _personal_onset_weights = {}
        _personal_dominant_onsets = []
        _personal_onset_weights_by_lang = {"en": {}, "ru": {}}
        return

    onset_counts = {}
    onset_counts_by_lang = {"en": {}, "ru": {}}
    for word in trigger_words:
        onset = _extract_onset(word)
        if onset:
            onset_counts[onset] = onset_counts.get(onset, 0) + 1
            # Per-language bucketing (#13)
            lang = detect_word_language(word)
            if lang in onset_counts_by_lang:
                onset_counts_by_lang[lang][onset] = onset_counts_by_lang[lang].get(onset, 0) + 1

    if not onset_counts:
        _personal_onset_weights = {}
        _personal_dominant_onsets = []
        _personal_onset_weights_by_lang = {"en": {}, "ru": {}}
        return

    total = sum(onset_counts.values())

    # Build weight map: floor (0.4) + personal boost (up to 0.5)
    # Onsets NOT in trigger history get 0.3 (below population prior)
    weights = {}
    for onset, count in onset_counts.items():
        frequency = count / total
        personal_boost = frequency * 0.5
        weights[onset] = min(0.4 + personal_boost, 0.9)

    _personal_onset_weights = weights

    # Per-language weights (#13)
    for lang, lang_counts in onset_counts_by_lang.items():
        lang_total = sum(lang_counts.values())
        if lang_total == 0:
            _personal_onset_weights_by_lang[lang] = {}
            continue
        lang_weights = {}
        for onset, count in lang_counts.items():
            frequency = count / lang_total
            personal_boost = frequency * 0.5
            lang_weights[onset] = min(0.4 + personal_boost, 0.9)
        _personal_onset_weights_by_lang[lang] = lang_weights

    # Track dominant onsets for insights (top 3 by count)
    ranked = sorted(onset_counts.items(), key=lambda x: -x[1])
    _personal_dominant_onsets = [
        {"onset": onset, "count": count, "pct": round(count / total * 100)}
        for onset, count in ranked[:3]
    ]
    if _personal_dominant_onsets:
        top = _personal_dominant_onsets[0]
        print(f"Onset weights: dominant /{top['onset']}/ ({top['pct']}% of {total} triggers)")

    # Persist to profile so weights survive restart + feed Firestore sync + clinical profile
    try:
        profile["onset_weights"] = dict(_personal_onset_weights)
        profile["onset_weights_by_lang"] = {
            lang: dict(w) for lang, w in _personal_onset_weights_by_lang.items()
        }
    except NameError:
        # profile not yet loaded (early startup path); skip persistence
        pass


# -- Onset frequency anomaly detection (covert avoidance signal) ──
# English content-word onset distribution (approximate, from SUBTLEX-US).
# Maps onset → expected % of content words starting with that onset.
# If a user's actual speech shows significantly fewer of an onset,
# they may be covertly avoiding it.
_ENGLISH_ONSET_BASELINE = {
    'b': 0.06, 'c': 0.05, 'ch': 0.02, 'cl': 0.01, 'cr': 0.01,
    'd': 0.05, 'f': 0.04, 'g': 0.03, 'gr': 0.01, 'h': 0.04,
    'j': 0.02, 'k': 0.03, 'l': 0.04, 'm': 0.04, 'n': 0.03,
    'p': 0.06, 'pl': 0.01, 'pr': 0.02, 'r': 0.04, 's': 0.07,
    'sh': 0.02, 'sp': 0.01, 'st': 0.03, 'str': 0.01, 'sw': 0.01,
    't': 0.06, 'th': 0.03, 'tr': 0.02, 'w': 0.04,
}
_onset_anomalies = []  # list of {onset, expected_pct, actual_pct, deficit_ratio}


def detect_onset_anomalies(sessions, min_sessions=30, min_content_words=200):
    """Detect onsets statistically underrepresented in user's actual speech.
    Compares user's content-word onset distribution against English baseline.
    Returns list of anomalous onsets (possible covert avoidance signals)."""
    global _onset_anomalies
    if len(sessions) < min_sessions:
        _onset_anomalies = []
        return []

    # Count all content-word onsets across sessions
    onset_counts = {}
    total_content = 0
    for s in sessions:
        raw = s.get("raw", "")
        if not raw:
            continue
        words = re.findall(r'\b\w+\b', raw.lower())
        for w in words:
            if w in FUNCTION_WORDS or len(w) < 2:
                continue
            total_content += 1
            # Extract onset (longest match)
            for length in (3, 2, 1):
                prefix = w[:length]
                if prefix in _ENGLISH_ONSET_BASELINE:
                    onset_counts[prefix] = onset_counts.get(prefix, 0) + 1
                    break

    if total_content < min_content_words:
        _onset_anomalies = []
        return []

    # Compare against baseline — flag onsets where user produces <40% of expected
    anomalies = []
    for onset, expected_pct in _ENGLISH_ONSET_BASELINE.items():
        if onset not in HIGH_RISK_ONSETS:
            continue  # only flag risky onsets
        actual_count = onset_counts.get(onset, 0)
        actual_pct = actual_count / total_content
        if expected_pct > 0.01:
            deficit_ratio = actual_pct / expected_pct
            if deficit_ratio < 0.40:  # user produces <40% of expected
                anomalies.append({
                    "onset": onset,
                    "expected_pct": round(expected_pct * 100, 1),
                    "actual_pct": round(actual_pct * 100, 1),
                    "deficit_ratio": round(deficit_ratio, 2),
                })

    anomalies.sort(key=lambda x: x["deficit_ratio"])
    _onset_anomalies = anomalies[:5]  # top 5 most avoided
    if _onset_anomalies:
        top = _onset_anomalies[0]
        print(f"Onset anomaly: /{top['onset']}/ at {top['actual_pct']}% vs expected {top['expected_pct']}% "
            f"(deficit {top['deficit_ratio']}x) -- possible covert avoidance")
    return _onset_anomalies


def predict_phonetic_risk(word, sentence_position=None, sentence_length=None):
    """Predict block risk using 5 linguistic features (Brown's 4 + frequency):
      1. Consonant-initial (onset matching, personalized weights)
      2. Content word vs function word
      3. Position early in sentence (higher risk)
      4. Longer word (higher risk)
      5. Word frequency (low-frequency = higher risk, FluencyBank 2023)

    Uses personalized onset weights when available (learned from user's
    trigger history), falls back to population priors otherwise.

    Optional sentence_position/sentence_length enable features 3-4.
    Without them, falls back to features 1-2-5 only (backward compatible).
    Returns 0.0-1.0 risk score."""
    w = word.lower().strip()
    if not w or w in FUNCTION_WORDS:
        return 0.1  # function words rarely trigger (Brown feature 2)
    score = 0.25  # base risk for content words (Brown feature 2)

    # Brown feature 1: consonant-initial words — onset matching
    # #13: use language-specific weights when available
    matched_onset = _extract_onset(w)
    if matched_onset:
        lang = detect_word_language(w)
        lang_weights = _personal_onset_weights_by_lang.get(lang, {})
        if lang_weights:
            score += lang_weights.get(matched_onset, 0.3)
        elif _personal_onset_weights:
            score += _personal_onset_weights.get(matched_onset, 0.3)
        else:
            score += 0.4
        # Boost for covert avoidance signal (onset statistically underrepresented)
        if _onset_anomalies:
            for anomaly in _onset_anomalies:
                if anomaly["onset"] == matched_onset:
                    score += 0.10  # this onset is being avoided — it's harder than triggers alone show
                    break
    # Unvoiced plosives/fricatives are harder than voiced
    if w[0] in 'ptksf':
        score += 0.05

    # Brown feature 3: position in sentence (earlier = higher risk)
    if sentence_position is not None and sentence_length is not None and sentence_length > 0:
        # First 30% of sentence gets max boost, decays linearly
        relative_pos = sentence_position / max(sentence_length, 1)
        position_boost = max(0.15 * (1.0 - relative_pos * 2.5), 0.0)
        score += position_boost

    # Brown feature 4: word length (longer = higher risk)
    if len(w) >= 7:
        score += 0.10
    elif len(w) >= 5:
        score += 0.05

    # Feature 5: word frequency (FluencyBank 2023 — low frequency = higher risk)
    # High-frequency content words are easier; rare/technical words are harder
    if w not in _HIGH_FREQ_WORDS:
        score += 0.10  # low-frequency word boost

    return min(score, 1.0)

def compute_brown_scores(text):
    """Score every word in text using all 4 Brown features with sentence context.
    Returns list of (word, risk_score) for all content words."""
    words = re.findall(r'\b\w+\b', text)
    n = len(words)
    scores = []
    for i, word in enumerate(words):
        risk = predict_phonetic_risk(word, sentence_position=i, sentence_length=n)
        scores.append((word, round(risk, 2)))
    return scores


def brown_peak_risk(text):
    """Return the single highest Brown risk score in a text.
    Useful for deciding endpointer patience / filter aggressiveness."""
    scores = compute_brown_scores(text)
    if not scores:
        return 0.0
    return max(s[1] for s in scores)


def predict_triggers_in_text(text, existing_triggers):
    """Score all content words in text, return predicted triggers above threshold.
    Uses full Brown's 4-feature scoring with sentence context."""
    words = re.findall(r'\b\w+\b', text)
    known = {t.lower() for t in existing_triggers}
    predicted = []
    n = len(words)
    for i, word in enumerate(words):
        clean = word.lower()
        if not clean or len(clean) < 2:
            continue
        risk = predict_phonetic_risk(clean, sentence_position=i, sentence_length=n)
        # Boost if the word shares an onset with a known trigger
        for trigger in known:
            if trigger[:2] == clean[:2] and clean != trigger:
                risk = min(risk + 0.2, 1.0)
                break
        if risk >= 0.6:
            predicted.append((clean, round(risk, 2)))
    return sorted(predicted, key=lambda x: -x[1])


# -- Clipboard Predictor ──────────────────────────────────────────
# Background thread monitors clipboard text, scores words via Brown's features,
# and pre-builds a Whisper initial_prompt bias with LLM-generated synonyms.
# Never blocks recording — the bias is always pre-computed and cached.
# Only activates in high-pressure situations (phone, interview, presentation).

_CLIPBOARD_POLL_INTERVAL = 4       # seconds between clipboard checks
_CLIPBOARD_CACHE_TTL = 300         # 5 minutes — cached bias validity
_CLIPBOARD_RISK_THRESHOLD = 0.55   # min avg risk to trigger LLM synonym call
_CLIPBOARD_TOP_N = 6               # top-N riskiest words sent to LLM
_CLIPBOARD_MIN_TRIGGERS = 2        # need at least this many high-risk words
_CLIPBOARD_HIGH_PRESSURE = {"high_stress"}


class ClipboardPredictor:
    """Zero-blocking clipboard-based speech predictor.

    Runs a daemon thread that:
    1. Polls clipboard every 4s
    2. Scores words locally via predict_phonetic_risk() (instant, no API)
    3. If risk is high AND situation is high-pressure → async LLM call for synonyms
    4. Caches result as Whisper initial_prompt bias

    get_prompt_bias() returns the cached bias or None. Never blocks."""

    def __init__(self):
        self._bias = None
        self._bias_ts = 0.0
        self._last_clipboard = ""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, name="clipboard-predictor", daemon=True
        )
        self._thread.start()
        print("ClipboardPredictor started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def get_prompt_bias(self):
        """Return cached Whisper initial_prompt bias if still fresh, else None."""
        with self._lock:
            if self._bias and (time.time() - self._bias_ts) < _CLIPBOARD_CACHE_TTL:
                return self._bias
        return None

    def invalidate(self):
        """Force re-evaluation — call when situation changes."""
        with self._lock:
            self._bias = None
            self._bias_ts = 0.0
            self._last_clipboard = ""

    def _loop(self):
        while not self._stop_event.wait(_CLIPBOARD_POLL_INTERVAL):
            try:
                self._tick()
            except Exception as e:
                pass  # never crash the background thread

    def _tick(self):
        # Only activate in high-pressure situations
        if current_situation not in _CLIPBOARD_HIGH_PRESSURE:
            with self._lock:
                self._bias = None
            return

        try:
            clipboard = pyperclip.paste() or ""
        except Exception:
            return

        # No change and cache still fresh — skip
        with self._lock:
            cache_fresh = (time.time() - self._bias_ts) < _CLIPBOARD_CACHE_TTL
        if clipboard == self._last_clipboard and cache_fresh:
            return
        self._last_clipboard = clipboard

        # Step 1: local risk scoring via compute_brown_scores (instant, no API)
        scores = compute_brown_scores(clipboard)
        if not scores:
            return

        # Deduplicate, keep highest score per word
        best = {}
        for word, risk in scores:
            wl = word.lower()
            if risk > best.get(wl, 0):
                best[wl] = risk
        top = sorted(best.items(), key=lambda x: x[1], reverse=True)[:_CLIPBOARD_TOP_N]
        high_risk = [(w, r) for w, r in top if r >= _CLIPBOARD_RISK_THRESHOLD]

        if len(high_risk) < _CLIPBOARD_MIN_TRIGGERS:
            with self._lock:
                self._bias = None
            return

        trigger_words = [w for w, _ in high_risk]
        log(f"CLIPBOARD triggers ({current_situation}): {trigger_words}", "info")

        # Step 2: async LLM synonym call (runs in THIS background thread, never blocks recording)
        bias = self._build_bias(trigger_words, current_situation)
        if bias:
            with self._lock:
                self._bias = bias
                self._bias_ts = time.time()
            log(f"CLIPBOARD bias cached ({len(bias)} chars)", "info")

    def _build_bias(self, triggers, situation):
        """Call LLM to get fluency-friendly synonyms for high-risk words."""
        try:
            dominant = sorted(_personal_onset_weights.items(), key=lambda x: x[1], reverse=True)[:3]
            dominant_str = ", ".join(f"/{o}/" for o, _ in dominant) if dominant else "plosives"

            prompt = (
                f"This speaker blocks on {dominant_str} consonants.\n"
                f"They are about to speak in a '{situation}' context.\n"
                f"Upcoming high-risk words: {', '.join(triggers)}.\n"
                f"For each, provide 1-2 fluency-friendly synonyms that start with "
                f"continuants (l, m, n, r, w, h) or vowels.\n"
                f"Format: word→synonym. Keep it under 40 words total. No explanations."
            )
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=80,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            synonyms = response.choices[0].message.content.strip()
            return (
                f"Speaker context ({situation}): {synonyms}. "
                f"Reconstruct intended words from context when speech is unclear."
            )
        except Exception as e:
            log(f"ClipboardPredictor LLM failed: {e}", "error")
            return None


_clipboard_predictor = None  # initialized after profile load

client = openai.OpenAI(api_key=API_KEY) if API_KEY else None

# Anthropic client for cross-vendor Falcon validation (different blind spots
# from OpenAI's reconstruction → catches errors a self-eval would miss).
try:
    import anthropic
    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
except ImportError:
    anthropic_client = None

# -- Google Sign-In / Backend reconstruction ─────────────────────
BACKEND_URL = "https://us-central1-bakers-agent.cloudfunctions.net/wim-reconstruct"
_firebase_id_token = None  # set by /api/auth when user signs in via Google
_auth_user = None          # {uid, email, displayName} from dashboard

def is_authenticated():
    """Check if user is signed in via Google (has a Firebase ID token)."""
    return _firebase_id_token is not None

def reconstruct_via_backend(raw_text, tone, layer, prof, situation="default", mode="SAFE",
                            whisper_low_conf=None, whisper_disagreements=None,
                            speech_severity_mod=0.0,
                            paralinguistic_events=None, prosodic_context=None,
                            language_code="en"):
    """Reconstruct via Cloud Function backend (uses server-side API key).
    Called when user is signed in via Google instead of using a local API key."""
    import urllib.request
    payload = {
        "raw": raw_text,
        "tone": tone,
        "layer": layer,
        "situation": situation,
        "mode": mode,
        "speech_severity_mod": speech_severity_mod,
        "language_code": language_code,
        "profile": {
            "vocabulary": prof.get("vocabulary", [])[:20],
            "corrections": dict(list(prof.get("corrections", {}).items())[:10]),
            "filler_words": prof.get("filler_words", [])[:25],
            "trigger_words": prof.get("trigger_words", [])[:30],
            "onset_weights": prof.get("onset_weights", {}),
            "covert_profile": prof.get("covert_profile", {}),
        },
    }
    if whisper_low_conf:
        payload["whisper_low_conf"] = whisper_low_conf[:5]
    if whisper_disagreements:
        payload["whisper_disagreements"] = whisper_disagreements[:5]
    if paralinguistic_events:
        payload["paralinguistic_events"] = paralinguistic_events
    if prosodic_context:
        payload["prosodic_context"] = prosodic_context

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BACKEND_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_firebase_id_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("clean", raw_text), result.get("falcon_ok", True), result
    except Exception as e:
        log(f"Backend reconstruct failed: {e}", "error")
        return None, False, {"error": str(e)}

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

def _redetect_mic():
    """Re-run mic detection when the cached DEVICE index goes stale."""
    global DEVICE, NATIVE_RATE, NEEDS_RESAMPLE, RESAMPLE_UP, RESAMPLE_DOWN
    DEVICE = None
    for i, dev in enumerate(sd.query_devices()):
        if PREFERRED_MIC.lower() in dev['name'].lower() and dev['max_input_channels'] > 0:
            DEVICE = i
            break
    if DEVICE is None:
        DEVICE = sd.default.device[0]
    device_info = sd.query_devices(DEVICE)
    NATIVE_RATE = int(device_info['default_samplerate'])
    NEEDS_RESAMPLE = NATIVE_RATE != TARGET_RATE
    if NEEDS_RESAMPLE:
        _g = gcd(TARGET_RATE, NATIVE_RATE)
        RESAMPLE_UP = TARGET_RATE // _g
        RESAMPLE_DOWN = NATIVE_RATE // _g

# -- The File (User Profile) ─────────────────────────────────────
# Bilingual filler sets — merged into profile on startup
KNOWN_FILLERS = {
    "en": ["um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
           "like", "you know", "I mean", "so", "well", "right",
           "basically", "literally", "actually", "honestly"],
    "ru": ["это", "ну", "нуу", "вот", "типа", "как бы", "значит", "короче",
           "ладно", "та", "э", "ээ", "эм", "слушай"],
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
    "preferences": {"tone": "casual", "layer": 2, "paralinguistic": False, "prosodic": False, "paralinguistic_transcribe": False}
}

def load_profile():
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data.pop("sessions", None)  # sessions live in SQLite now
            return data
        except (json.JSONDecodeError, IOError):
            pass
    p = dict(DEFAULT_PROFILE)
    p["created"] = datetime.now().isoformat()
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

_profile_lock = threading.Lock()
_profile_switch_epoch = 0  # incremented on every switch_profile(); background threads check before saving

def save_profile(prof, _epoch=None):
    """Thread-safe atomic profile write. Lock prevents concurrent .tmp corruption.
    If _epoch is given (from a background thread), skip save if a profile switch occurred."""
    if _epoch is not None and _epoch != _profile_switch_epoch:
        return  # profile was switched since this thread launched — discard stale write
    with _profile_lock:
        PROFILE_DIR.mkdir(exist_ok=True)
        tmp_path = PROFILE_PATH.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(prof, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(PROFILE_PATH)
    # FIRESTORE DIRECT PUBLISH HOOK — REMOVED 2026-04-24
    # The original code did `from lavrentiy.firestore_publisher import ...`. When
    # this script runs as `lavrentiy.py` (the entry-point script, sys.modules
    # name is __main__ not lavrentiy), `import lavrentiy` finds lavrentiy.py
    # again and RE-EXECUTES the entire module — which re-runs the mutex check
    # (sees the original engine on port 7878, prints "Lavrentiy is already
    # running") and calls os._exit(0), killing the original process.
    #
    # That's the silent engine-death bug we've been chasing. Sign-in (or any
    # other code path that calls save_profile) was triggering it. Symptoms:
    # (a) two STARTUP entries with same PID in lifecycle.log, (b) "[SWP] A"
    # logged but never "[SWP] B" — the recursive import killed it inside
    # save_profile before it could continue.
    #
    # The cross-device profile sync happens via the cloud function path below
    # (sync_profile_to_firestore), which uses urllib + the BACKEND_URL — no
    # broken `import lavrentiy.*` involved. So nothing of value is lost.

    # Sync to Firestore in background (debounced, fire-and-forget)
    threading.Thread(target=sync_profile_to_firestore, args=(prof,), daemon=True).start()

_last_sync_ts = 0

def sync_profile_to_firestore(prof):
    """Push learned profile fields to Firestore via Cloud Function (fire-and-forget)."""
    global _last_sync_ts
    if not is_authenticated() or _auth_user is None:
        return
    # Debounce: skip if last sync was less than 60s ago
    now = time.time()
    if now - _last_sync_ts < 60:
        return
    _last_sync_ts = now
    try:
        import urllib.request
        payload = {
            "action": "sync_profile",
            "profile": {
                "trigger_words": prof.get("trigger_words", [])[:30],
                "onset_weights": prof.get("onset_weights", {}),
                "covert_profile": prof.get("covert_profile", {}),
                "filler_words": prof.get("filler_words", [])[:25],
                "vocabulary": prof.get("vocabulary", [])[:20],
                "corrections": dict(list(prof.get("corrections", {}).items())[:10]),
            },
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            BACKEND_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_firebase_id_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        log("Profile synced to Firestore", "info")
    except Exception as e:
        log(f"Profile sync failed (non-fatal): {str(e)[:80]}", "warn")


def _snapshot_profile(prof):
    """Save timestamped backup. Keep last 5."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"profile_{ts}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)
    for old in sorted(BACKUP_DIR.glob("profile_*.json"))[:-5]:
        old.unlink()

def list_profiles():
    """Return sorted list of available profile names."""
    PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
    names = []
    for d in sorted(PROFILES_ROOT.iterdir()):
        if d.is_dir() and (d / "profile.json").exists():
            names.append(d.name)
    if not names:
        names.append(DEFAULT_PROFILE_NAME)
    return names

def switch_profile(name):
    """Switch to a different user profile. Saves current, closes DB, loads new."""
    global _active_profile_name, PROFILE_DIR, PROFILE_PATH, DB_PATH, BACKUP_DIR
    global profile, _db, _profile_switch_epoch
    global _shadow_history, _onset_anomalies, _personal_onset_weights
    global _personal_onset_weights_by_lang, _personal_dominant_onsets
    global _last_speech_metrics, _last_low_conf_segments, _last_avg_logprob
    global _last_paralinguistic_events, _last_speaker_state
    global _redo_count, _block_count, _decay_counter
    global learn_events, learn_status

    name = name.strip()
    if not name or '/' in name or '\\' in name or '..' in name:
        raise ValueError(f"Invalid profile name: {name}")

    log(f"[SWP] A: enter switch_profile('{name}')", "info")
    save_profile(profile)
    log(f"[SWP] B: save_profile done", "info")

    _profile_switch_epoch += 1
    log(f"[SWP] C: epoch bumped", "info")

    log(f"[SWP] D: acquiring _db_lock", "info")
    with _db_lock:
        log(f"[SWP] E: _db_lock acquired", "info")
        try:
            _db.close()
        except Exception as _e:
            log(f"[SWP] F: _db.close exception (ignored): {_e}", "warn")
        log(f"[SWP] G: _db closed", "info")

        _active_profile_name = name
        PROFILE_DIR, PROFILE_PATH, DB_PATH, BACKUP_DIR = _resolve_profile_paths(name)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _write_active_profile_name(name)
        log(f"[SWP] H: paths updated, active_profile written", "info")

        profile = load_profile()
        log(f"[SWP] I: load_profile done", "info")
        profile = migrate_profile(profile)
        log(f"[SWP] J: migrate_profile done", "info")
        if normalize_profile(profile):
            save_profile(profile)
        log(f"[SWP] K: normalize+save done", "info")
        migrate_fillers(profile)
        log(f"[SWP] L: migrate_fillers done", "info")
        learn_onset_weights(profile.get("trigger_words", []))
        log(f"[SWP] M: learn_onset_weights done", "info")

        _db = _init_db(DB_PATH)
        log(f"[SWP] N: _init_db done", "info")

    # Reset transient state
    _shadow_history.clear() if isinstance(_shadow_history, list) else None
    _onset_anomalies.clear() if isinstance(_onset_anomalies, list) else None
    _last_low_conf_segments.clear() if isinstance(_last_low_conf_segments, list) else None
    _last_paralinguistic_events.clear() if isinstance(_last_paralinguistic_events, list) else None
    _last_speech_metrics.clear() if isinstance(_last_speech_metrics, dict) else None
    _last_avg_logprob = 0.0
    _last_speaker_state = ""
    _redo_count = 0
    _block_count = 0
    _decay_counter = 0
    learn_events.clear() if isinstance(learn_events, list) else None
    # Reset learn_status with expected keys — .clear() would cause KeyError
    # when learn_from_sessions later does learn_status["total_learned"] += n
    if isinstance(learn_status, dict):
        learn_status.update({"last_run": None, "total_learned": 0, "next_in": LEARN_EVERY})

    try:
        print(f"Switched to profile: {name}")
    except Exception:
        pass
    return name

def create_profile(name):
    """Create a new blank profile. Does NOT switch to it."""
    name = name.strip()
    if not name or '/' in name or '\\' in name or '..' in name:
        raise ValueError(f"Invalid profile name: {name}")
    pdir = PROFILES_ROOT / name
    if pdir.exists():
        raise ValueError(f"Profile '{name}' already exists")
    pdir.mkdir(parents=True, exist_ok=True)
    p = dict(DEFAULT_PROFILE)
    p["created"] = datetime.now().isoformat()
    p["corrections"] = {}
    p["trigger_words"] = list(DEFAULT_PROFILE["trigger_words"])
    p["filler_words"] = list(DEFAULT_PROFILE["filler_words"])
    p["vocabulary"] = list(DEFAULT_PROFILE["vocabulary"])
    p["preferences"] = dict(DEFAULT_PROFILE["preferences"])
    with open(pdir / "profile.json", 'w', encoding='utf-8') as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    return name

def _norm_str(s, max_len=100):
    """Strip whitespace, cap length."""
    if not isinstance(s, str):
        return ""
    return s.strip()[:max_len]

def _dedupe_list(items, max_items=MAX_PROFILE_ITEMS, max_len=100):
    """Dedupe case-insensitively, strip, drop empties, cap count."""
    seen = set()
    result = []
    for item in items:
        if not isinstance(item, str):
            continue
        clean = item.strip()[:max_len]
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            result.append(clean)
        if len(result) >= max_items:
            break
    return result

def _norm_corrections(corr, max_items=MAX_PROFILE_ITEMS, max_len=100):
    """Normalize corrections: strip, dedupe by lowercase key, drop empties."""
    result = {}
    seen = set()
    for k, v in corr.items():
        nk = _norm_str(k, max_len)
        nv = _norm_str(v, max_len)
        if not nk or not nv:
            continue
        lk = nk.lower()
        if lk in seen:
            continue
        seen.add(lk)
        result[nk] = nv
        if len(result) >= max_items:
            break
    return result

def _migrate_candidate_corrections(cand):
    """Convert v2 candidate_corrections {right, count} to v3 {votes, total}."""
    migrated = {}
    for key, entry in cand.items():
        if isinstance(entry, dict) and "right" in entry and "votes" not in entry:
            count = entry.get("count", 1)
            migrated[key] = {"votes": {entry["right"]: count}, "total": count}
        else:
            migrated[key] = entry
    return migrated

def normalize_profile(prof):
    """Normalize all profile data in-place. Returns True if anything changed."""
    changed = False
    for key in ('trigger_words', 'filler_words', 'vocabulary'):
        if key in prof:
            cleaned = _dedupe_list(prof[key])
            if cleaned != prof[key]:
                prof[key] = cleaned
                changed = True
    if 'corrections' in prof:
        cleaned = _norm_corrections(prof['corrections'])
        if cleaned != prof['corrections']:
            prof['corrections'] = cleaned
            changed = True
    return changed

def migrate_profile(prof):
    """Upgrade profile schema to current version."""
    v = prof.get("version", 1)
    if v < PROFILE_VERSION:
        _snapshot_profile(prof)
        prof.setdefault("candidate_corrections", {})
        prof.setdefault("candidate_fillers", {})
        prof.setdefault("candidate_vocabulary", {})
        # v2 → v3: convert candidate_corrections to vote-based format
        if prof.get("candidate_corrections"):
            prof["candidate_corrections"] = _migrate_candidate_corrections(
                prof["candidate_corrections"])
        # v3 → v4: per-language trigger profiles (#13)
        if v < 4 and "trigger_words_by_lang" not in prof:
            triggers = prof.get("trigger_words", [])
            by_lang = {"en": [], "ru": []}
            for word in triggers:
                lang = detect_word_language(word)
                if lang in by_lang:
                    by_lang[lang].append(word)
                else:
                    by_lang["en"].append(word)  # default to English
            prof["trigger_words_by_lang"] = by_lang
            print(f"Profile v4: split {len(triggers)} triggers -> en:{len(by_lang['en'])} ru:{len(by_lang['ru'])}")
        normalize_profile(prof)
        prof["version"] = PROFILE_VERSION
        save_profile(prof)
    return prof

def log_session(prof, raw, output, tone, layer, decision=None, timings=None,
                situation=None, disf_counts=None, exposure=None, edit_dist=None,
                speech_metrics=None, lang=None, paralinguistic_events=None,
                prosodic_summary=None):
    ts = datetime.now().isoformat()
    falcon = decision["falcon_ok"] if decision else True
    words = len(output.split())
    sit = situation or current_situation
    # Trigger-word event detection — record which of the user's profile triggers
    # actually appeared in this session's raw transcript. Lightweight: simple
    # case-insensitive substring scan, no API calls. Powers per-trigger event
    # counts in the Weekly Report and Insights tab.
    triggers_fired = []
    try:
        raw_lower = (raw or "").lower()
        for trig in (prof.get("trigger_words", []) or []):
            t_norm = (trig or "").strip().lower()
            if t_norm and t_norm in raw_lower:
                triggers_fired.append(trig)
    except Exception:
        triggers_fired = []
    with _db_lock:
        _db.execute(
            "INSERT INTO sessions (ts, raw, out, tone, layer, words, falcon, decision, timings, "
            "situation, disfluency_counts, exposure_difficulty, editorial_distance, "
            "speech_metrics, lang, paralinguistic_events, prosodic_summary, triggers_fired) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, raw, output, tone, layer, words, int(falcon),
             json.dumps(decision) if decision else None,
             json.dumps(timings) if timings else None,
             sit,
             json.dumps(disf_counts) if disf_counts else None,
             json.dumps(exposure) if exposure else None,
             json.dumps(edit_dist) if edit_dist else None,
             json.dumps(speech_metrics) if speech_metrics else None,
             lang or 'en',
             json.dumps(paralinguistic_events) if paralinguistic_events else None,
             json.dumps(prosodic_summary) if prosodic_summary else None,
             json.dumps(triggers_fired) if triggers_fired else None)
        )
        _db.commit()


def archive_session_audio(tmp_path, raw_text, output_text, layer, situation):
    """Save session audio + transcript pair for future Whisper fine-tuning.
    Each session becomes one training sample: (audio.wav, metadata.json)."""
    if not ARCHIVE_AUDIO:
        return
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        # Check disk budget
        if ARCHIVE_DIR.exists():
            total_bytes = sum(f.stat().st_size for f in ARCHIVE_DIR.rglob("*") if f.is_file())
            if total_bytes > ARCHIVE_MAX_MB * 1024 * 1024:
                log(f"Audio archive at {total_bytes // (1024*1024)}MB — paused (limit: {ARCHIVE_MAX_MB}MB)", "info")
                return
        # Timestamp-based filename
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_dest = ARCHIVE_DIR / f"{ts}.wav"
        meta_dest = ARCHIVE_DIR / f"{ts}.json"
        # Copy WAV (don't move — original still needed for cleanup)
        shutil.copy2(tmp_path, wav_dest)
        # Detect disfluency events in raw text (regex-based, zero cost)
        disfluency_events = []
        for m in _HYPHEN_STUTTER.finditer(raw_text):
            disfluency_events.append({"type": "sound_rep", "text": m.group()})
        for m in _WORD_REPEAT.finditer(raw_text):
            disfluency_events.append({"type": "word_rep", "text": m.group()})

        # Save transcript pair with disfluency labels
        meta = {
            "timestamp": datetime.now().isoformat(),
            "raw_whisper": raw_text,
            "corrected_output": output_text,
            "layer": layer,
            "situation": situation,
            "disfluency_events": disfluency_events,
        }
        with open(meta_dest, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        log(f"Archived session audio: {wav_dest.name}", "info")
    except Exception as e:
        log(f"Audio archive failed (non-fatal): {e}", "error")


# -- Calibration mode ────────────────────────────────────────────
_calibration_state = {
    "active": False,
    "started_at": None,
    "completed": [],
    "skipped": [],
    "current_prompt": None
}


def calibration_status():
    """Return calibration progress."""
    total = len(CALIBRATION_PROMPTS)
    done = len(_calibration_state["completed"])
    skipped = len(_calibration_state["skipped"])
    remaining = total - done - skipped
    existing_wavs = 0
    if CALIBRATION_DIR.exists():
        existing_wavs = len(list(CALIBRATION_DIR.glob("*.wav")))
    return {
        "active": _calibration_state["active"],
        "total_prompts": total,
        "completed": done,
        "skipped": skipped,
        "remaining": remaining,
        "pct": round(done / total * 100) if total else 0,
        "existing_samples": existing_wavs,
        "ready_for_finetuning": existing_wavs >= 50,
        "categories": list({p["category"] for p in CALIBRATION_PROMPTS}),
        "started_at": _calibration_state["started_at"],
    }


def calibration_next_prompt():
    """Get the next uncompleted, unskipped prompt."""
    done_ids = set(_calibration_state["completed"]) | set(_calibration_state["skipped"])
    for p in CALIBRATION_PROMPTS:
        if p["id"] not in done_ids:
            _calibration_state["current_prompt"] = p["id"]
            return p
    return None


def calibration_save_audio(prompt_id, audio_data, sample_rate):
    """Save calibration audio with ground-truth alignment."""
    prompt = next((p for p in CALIBRATION_PROMPTS if p["id"] == prompt_id), None)
    if not prompt:
        return {"error": "unknown prompt_id"}
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    base = f"cal_{prompt_id:03d}_{prompt['category']}"
    wav_path = CALIBRATION_DIR / f"{base}.wav"
    meta_path = CALIBRATION_DIR / f"{base}.json"
    sf.write(str(wav_path), audio_data, sample_rate)
    # Run through local ASR to capture raw transcription for WER comparison
    whisper_raw = ""
    try:
        if _local_transcribe_fn is not None:
            r = _local_transcribe_fn(str(wav_path), 0.0, None, LANGUAGE, LOCAL_WHISPER_MODEL_SIZE)
            whisper_raw = r["text"]
            stats_inc("local_transcriptions")
        else:
            stats_inc("local_transcribe_unavailable")
    except Exception as e:
        log(f"Calibration local ASR pass failed: {e}", "error")
    wer_val = None
    if whisper_raw:
        wer_val, _, _, _ = compute_wer(prompt["text"], whisper_raw)
    meta = {
        "prompt_id": prompt_id,
        "category": prompt["category"],
        "ground_truth": prompt["text"],
        "whisper_raw": whisper_raw,
        "wer": round(wer_val, 4) if wer_val is not None else None,
        "timestamp": datetime.now().isoformat(),
        "sample_rate": sample_rate,
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    if prompt_id not in _calibration_state["completed"]:
        _calibration_state["completed"].append(prompt_id)
    wer_pct = f" (WER: {round(wer_val * 100, 1)}%)" if wer_val is not None else ""
    log(f"Calibration #{prompt_id}: saved{wer_pct}", "info")
    return {
        "saved": True, "prompt_id": prompt_id,
        "whisper_raw": whisper_raw, "ground_truth": prompt["text"],
        "wer": round(wer_val, 4) if wer_val is not None else None,
    }


def calibration_load_progress():
    """Restore calibration progress from disk."""
    if not CALIBRATION_DIR.exists():
        return
    for meta_file in CALIBRATION_DIR.glob("*.json"):
        try:
            with open(meta_file, 'r') as f:
                data = json.load(f)
            pid = data.get("prompt_id")
            if pid and pid not in _calibration_state["completed"]:
                _calibration_state["completed"].append(pid)
        except Exception:
            pass


calibration_load_progress()


# -- Severity score (research: isWER rises with severity) ───────
def compute_severity_score():
    """Compute stuttering severity from calibration WER data.

    Severity bands (based on FluencyBank/clinical research):
      mild:     WER < 10%
      moderate: WER 10-25%
      severe:   WER 25-40%
      very_severe: WER > 40%

    Returns dict with overall score, per-category breakdown,
    and trend (if multiple calibration runs exist).
    """
    if not CALIBRATION_DIR.exists():
        return {"severity": None, "message": "no calibration data"}

    wers_by_category = {}
    all_wers = []

    for meta_file in sorted(CALIBRATION_DIR.glob("cal_*.json")):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            wer = data.get("wer")
            cat = data.get("category", "unknown")
            if wer is not None:
                all_wers.append(wer)
                wers_by_category.setdefault(cat, []).append(wer)
        except Exception:
            continue

    if not all_wers:
        return {"severity": None, "message": "no WER data in calibration"}

    avg_wer = sum(all_wers) / len(all_wers)

    # Severity classification
    if avg_wer < 0.10:
        band = "mild"
    elif avg_wer < 0.25:
        band = "moderate"
    elif avg_wer < 0.40:
        band = "severe"
    else:
        band = "very_severe"

    # Per-category averages (sorted worst-first)
    cat_scores = {}
    for cat, wers in wers_by_category.items():
        cat_scores[cat] = round(sum(wers) / len(wers), 4)
    cat_sorted = dict(sorted(cat_scores.items(), key=lambda x: -x[1]))

    # Hardest categories (top 3 by WER)
    hardest = list(cat_sorted.keys())[:3]

    return {
        "severity": band,
        "avg_wer": round(avg_wer, 4),
        "avg_wer_pct": round(avg_wer * 100, 1),
        "samples": len(all_wers),
        "by_category": cat_sorted,
        "hardest_categories": hardest,
    }


# -- Synthetic disfluency augmentation (Mujtaba24 Interspeech) ──
import random
import base64

AUGMENT_DIR = CALIBRATION_DIR / "augmented"
AUGMENT_VARIANTS = 4              # synthetic variants per real sample
AUGMENT_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
_augment_lock = threading.Lock()
_augment_state = {
    "running": False,
    "total": 0,
    "completed": 0,
    "errors": 0,
    "last_run": None,
}

# Interjections drawn from real stuttered speech corpora
_INTERJECTIONS = ["um", "uh", "like", "you know", "I mean", "so", "well", "ah"]
_RU_INTERJECTIONS = ["э", "ну", "это", "вот", "значит", "как бы", "типа"]


def inject_disfluencies(text, variant_idx=0):
    """Inject text-level disfluencies into a fluent transcript.

    Disfluency types (per Mujtaba24 Interspeech):
      - Word repetitions:    repeat a word 1-6 extra times
      - Phrase repetitions:  repeat a 2-3 word phrase 1-5 times
      - Interjection inserts: inject "um", "uh", etc. 1-7 times

    Each call produces a different random pattern via seed = variant_idx.
    Returns the disfluent text string.
    """
    rng = random.Random(hash(text) + variant_idx)
    words = text.split()
    if len(words) < 3:
        return text

    # Decide which disfluencies to apply (at least 1, up to all 3)
    types = ["word_rep", "phrase_rep", "interjection"]
    n_types = rng.randint(1, 3)
    active = rng.sample(types, n_types)
    result = list(words)

    # 1. Word repetitions: pick 1-2 positions, repeat the word 1-6 extra times
    if "word_rep" in active:
        n_reps = rng.randint(1, min(2, len(result) - 1))
        positions = rng.sample(range(len(result)), n_reps)
        for pos in sorted(positions, reverse=True):
            count = rng.randint(1, 6)
            word = result[pos]
            result[pos:pos+1] = [word] * (count + 1)

    # 2. Phrase repetitions: pick a 2-3 word span, repeat 1-5 times
    if "phrase_rep" in active and len(result) >= 4:
        span_len = rng.randint(2, min(3, len(result) // 2))
        max_start = len(result) - span_len
        if max_start > 0:
            start = rng.randint(0, max_start)
            phrase = result[start:start + span_len]
            count = rng.randint(1, 5)
            insert = []
            for _ in range(count):
                insert.extend(phrase)
            result[start:start] = insert

    # 3. Interjection insertions: insert 1-7 interjections at random positions
    if "interjection" in active:
        interjections = _INTERJECTIONS
        n_inserts = rng.randint(1, min(7, len(result)))
        for _ in range(n_inserts):
            pos = rng.randint(0, len(result))
            filler = rng.choice(interjections)
            result.insert(pos, filler)

    return " ".join(result)


def augment_calibration_data():
    """Generate synthetic disfluent training data from completed calibration prompts.

    For each real calibration sample:
      1. Load ground truth text
      2. Generate AUGMENT_VARIANTS disfluent text variants
      3. Synthesize each via OpenAI TTS API
      4. Save WAV + metadata JSON in AUGMENT_DIR

    Multiplies 60 real samples → 240 synthetic training pairs.
    Runs synchronously (called from background thread via API).
    """
    with _augment_lock:
        if _augment_state["running"]:
            return {"error": "augmentation already running"}
        _augment_state["running"] = True
        _augment_state["errors"] = 0
        _augment_state["completed"] = 0

    # Collect completed calibration samples
    if not CALIBRATION_DIR.exists():
        _augment_state["running"] = False
        return {"error": "no calibration data — run calibration first"}

    cal_metas = []
    for meta_file in sorted(CALIBRATION_DIR.glob("cal_*.json")):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("ground_truth"):
                cal_metas.append(data)
        except Exception:
            continue

    if not cal_metas:
        _augment_state["running"] = False
        return {"error": "no completed calibration samples found"}

    AUGMENT_DIR.mkdir(parents=True, exist_ok=True)
    total = len(cal_metas) * AUGMENT_VARIANTS
    _augment_state["total"] = total
    log(f"Augmentation starting: {len(cal_metas)} samples × {AUGMENT_VARIANTS} variants = {total} synthetic pairs", "info")

    rng = random.Random(42)
    generated = 0

    for meta in cal_metas:
        pid = meta["prompt_id"]
        ground_truth = meta["ground_truth"]
        category = meta.get("category", "unknown")

        for v in range(AUGMENT_VARIANTS):
            # Check if already generated
            base = f"aug_{pid:03d}_v{v}_{category}"
            wav_path = AUGMENT_DIR / f"{base}.wav"
            meta_path = AUGMENT_DIR / f"{base}.json"
            if wav_path.exists() and meta_path.exists():
                generated += 1
                _augment_state["completed"] = generated
                continue

            # Generate disfluent text
            disfluent_text = inject_disfluencies(ground_truth, variant_idx=v)

            # Synthesize via OpenAI TTS
            voice = AUGMENT_VOICES[v % len(AUGMENT_VOICES)]
            try:
                response = client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=disfluent_text,
                    response_format="wav",
                    speed=rng.uniform(0.85, 1.15),  # slight speed variation
                )
                # Save WAV
                response.stream_to_file(str(wav_path))
                stats_inc("api_calls")

                # Run through local ASR to capture how the engine handles disfluent audio
                whisper_raw = ""
                try:
                    if _local_transcribe_fn is not None:
                        r = _local_transcribe_fn(str(wav_path), 0.0, None, LANGUAGE, LOCAL_WHISPER_MODEL_SIZE)
                        whisper_raw = r["text"]
                        stats_inc("local_transcriptions")
                    else:
                        stats_inc("local_transcribe_unavailable")
                except Exception as e:
                    log(f"Augment local ASR pass failed for {base}: {e}", "error")

                # Save metadata
                aug_meta = {
                    "prompt_id": pid,
                    "variant": v,
                    "category": category,
                    "ground_truth": ground_truth,
                    "disfluent_text": disfluent_text,
                    "whisper_raw": whisper_raw,
                    "voice": voice,
                    "type": "augmented",
                    "timestamp": datetime.now().isoformat(),
                }
                # Compute WER if we got Whisper output
                if whisper_raw:
                    wer_val, subs, dels, ins = compute_wer(ground_truth, whisper_raw)
                    aug_meta["wer"] = round(wer_val, 4)
                    aug_meta["wer_detail"] = {"substitutions": subs, "deletions": dels, "insertions": ins}

                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump(aug_meta, f, indent=2, ensure_ascii=False)

                generated += 1
                _augment_state["completed"] = generated

                if generated % 10 == 0:
                    log(f"Augmentation progress: {generated}/{total}", "info")

            except Exception as e:
                _augment_state["errors"] += 1
                log(f"Augment TTS failed for {base}: {e}", "error")
                continue

    _augment_state["running"] = False
    _augment_state["last_run"] = datetime.now().isoformat()
    log(f"Augmentation complete: {generated}/{total} synthetic pairs ({_augment_state['errors']} errors)", "info")
    return {
        "completed": generated,
        "total": total,
        "errors": _augment_state["errors"],
        "augment_dir": str(AUGMENT_DIR),
    }


def augment_status():
    """Return augmentation stats."""
    aug_count = 0
    aug_bytes = 0
    if AUGMENT_DIR.exists():
        aug_count = len(list(AUGMENT_DIR.glob("aug_*.wav")))
        aug_bytes = sum(f.stat().st_size for f in AUGMENT_DIR.rglob("*") if f.is_file())

    cal_count = len(_calibration_state["completed"])
    potential = cal_count * AUGMENT_VARIANTS

    return {
        "running": _augment_state["running"],
        "augmented_samples": aug_count,
        "real_samples": cal_count,
        "potential_total": potential,
        "multiplier": f"{aug_count + cal_count}x" if cal_count else "0x",
        "size_mb": round(aug_bytes / (1024 * 1024), 1),
        "errors": _augment_state["errors"],
        "last_run": _augment_state["last_run"],
        "progress": _augment_state["completed"],
        "progress_total": _augment_state["total"],
        "ready": aug_count >= 50,
    }


profile = load_profile()
profile = migrate_profile(profile)
if normalize_profile(profile):
    save_profile(profile)
_new_fillers = migrate_fillers(profile)
if _new_fillers:
    print(f"Added {len(_new_fillers)} bilingual fillers: {', '.join(_new_fillers)}")

# Initialize personalized onset weights from existing trigger data
learn_onset_weights(profile.get("trigger_words", []))

# Start clipboard predictor (background thread, never blocks)
_clipboard_predictor = ClipboardPredictor()
_clipboard_predictor.start()

# -- SQLite session history ───────────────────────────────────────
_db_lock = threading.Lock()

def _init_db(db_path=None):
    """Initialize (or reinitialize) the SQLite database connection. Thread-safe."""
    if db_path is None:
        db_path = DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path), check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, raw TEXT NOT NULL, out TEXT NOT NULL,
            tone TEXT NOT NULL, layer INTEGER NOT NULL,
            words INTEGER NOT NULL, falcon INTEGER NOT NULL DEFAULT 1,
            decision TEXT, timings TEXT, situation TEXT DEFAULT 'default'
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(ts)")
    for col_sql in [
        "ALTER TABLE sessions ADD COLUMN situation TEXT DEFAULT 'default'",
        "ALTER TABLE sessions ADD COLUMN disfluency_counts TEXT",
        "ALTER TABLE sessions ADD COLUMN exposure_difficulty TEXT",
        "ALTER TABLE sessions ADD COLUMN editorial_distance REAL",
        "ALTER TABLE sessions ADD COLUMN speech_metrics TEXT",
        "ALTER TABLE sessions ADD COLUMN lang TEXT DEFAULT 'en'",
        "ALTER TABLE sessions ADD COLUMN paralinguistic_events TEXT",
        "ALTER TABLE sessions ADD COLUMN prosodic_summary TEXT",
        "ALTER TABLE sessions ADD COLUMN triggers_fired TEXT",
    ]:
        try:
            db.execute(col_sql)
        except sqlite3.OperationalError:
            pass
    db.commit()
    return db

PROFILE_DIR.mkdir(parents=True, exist_ok=True)
_db = _init_db(DB_PATH)

# One-time migration: move sessions from profile.json into SQLite
_migrated_path = PROFILE_DIR / ".sessions_migrated"
if not _migrated_path.exists():
    _old_sessions = []
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as _f:
                _old_data = json.load(_f)
            _old_sessions = _old_data.get("sessions", [])
        except (json.JSONDecodeError, IOError):
            pass
    if _old_sessions:
        with _db_lock:
            _db.executemany(
                "INSERT INTO sessions (ts, raw, out, tone, layer, words, falcon, decision, timings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(s.get("ts", ""), s.get("raw", ""), s.get("out", ""),
                  s.get("tone", "casual"), s.get("layer", 1),
                  s.get("words", 0), int(s.get("falcon", True)),
                  json.dumps(s["decision"]) if "decision" in s else None,
                  json.dumps(s["timings"]) if "timings" in s else None)
                 for s in _old_sessions]
            )
            _db.commit()
        print(f"Migrated {len(_old_sessions)} sessions to SQLite")
        # Strip sessions from profile.json
        if PROFILE_PATH.exists():
            try:
                with open(PROFILE_PATH, 'r', encoding='utf-8') as _f:
                    _pdata = json.load(_f)
                if "sessions" in _pdata:
                    del _pdata["sessions"]
                    with open(PROFILE_PATH, 'w', encoding='utf-8') as _f:
                        json.dump(_pdata, _f, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, IOError):
                pass
    _migrated_path.touch()

def db_get_sessions(limit=50, offset=0):
    """Fetch recent sessions from SQLite, newest first."""
    with _db_lock:
        rows = _db.execute(
            "SELECT ts, raw, out, tone, layer, words, falcon, decision, timings, "
            "situation, disfluency_counts, exposure_difficulty, editorial_distance, "
            "speech_metrics, lang, prosodic_summary "
            "FROM sessions ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    result = []
    for row in rows:
        ts, raw, out, tone, layer, words, falcon, decision, timings, \
            situation, disf, exposure, edit_dist, spmet, lang, prosodic_sum = row
        entry = {"ts": ts, "raw": raw, "out": out, "tone": tone,
                 "layer": layer, "words": words, "falcon": bool(falcon),
                 "situation": situation or "default",
                 "lang": lang or "en"}
        if decision:
            entry["decision"] = json.loads(decision)
        if timings:
            entry["timings"] = json.loads(timings)
        if disf:
            entry["disfluency_counts"] = json.loads(disf)
        if exposure:
            entry["exposure"] = json.loads(exposure)
        if edit_dist is not None:
            entry["editorial_distance"] = edit_dist
        if spmet:
            entry["speech_metrics"] = json.loads(spmet)
        if prosodic_sum:
            entry["prosodic_summary"] = json.loads(prosodic_sum)
        result.append(entry)
    return result

def db_session_count():
    """Total number of sessions stored."""
    with _db_lock:
        return _db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

# -- State ────────────────────────────────────────────────────────
recording = []
is_recording = False
stream = None
# Pre-roll buffer: always-listening ring buffer captures last N seconds of audio
# so F9 presses catch the user's first word (mic stream startup takes ~150-500ms)
PREROLL_SEC = 0.5
_preroll_buffer = []
_preroll_max_frames = None  # computed on startup from NATIVE_RATE
lock = threading.Lock()
state = 'idle'

current_tone = profile["preferences"].get("tone", "casual")
current_layer = profile["preferences"].get("layer", 2)
current_mode = profile["preferences"].get("mode", MODE)
paralinguistic_enabled = profile["preferences"].get("paralinguistic", False)
paralinguistic_transcribe = profile["preferences"].get("paralinguistic_transcribe", False)
prosodic_enabled = profile["preferences"].get("prosodic", False)
quiet_mode_enabled = profile["preferences"].get("quiet_mode", False)

# Migration: Layer 5 -> Layer 4 + toggles
if current_layer >= 5:
    current_layer = 4
    paralinguistic_enabled = True
    prosodic_enabled = True
    profile["preferences"]["layer"] = 4
    profile["preferences"]["paralinguistic"] = True
    profile["preferences"]["prosodic"] = True
    save_profile(profile)
tap_times = []
target_hwnd = None
last_paste_time = 0
last_stop_time = 0
is_pasting = False
# Command Mode: highlight text + F8 + speak command → transforms selection
is_command_mode = False
command_selected_text = ""
# Network status tracking (for Wi-Fi bar indicator in stats bar)
_last_api_ok_ts = 0
_last_api_error_ts = 0
_last_api_error_msg = ""
stats = {
    "words": 0, "sessions": 0, "chars": 0,
    "start_time": time.time(),
    "api_calls": 0, "falcon_rejects": 0,
    "multi_temp_votes": 0, "multi_temp_disagreements": 0,
    "local_transcriptions": 0,
    "repetition_loops": 0
}
_stats_lock = threading.Lock()

def stats_inc(key, n=1):
    """Thread-safe increment of a stats counter."""
    global _last_api_ok_ts
    with _stats_lock:
        stats[key] = stats.get(key, 0) + n
    # Track network status: any API call increment = API reachable
    if key == "api_calls":
        _last_api_ok_ts = time.time()

def track_api_error(msg=""):
    """Record that an API call failed — used for network-status Wi-Fi indicator."""
    global _last_api_error_ts, _last_api_error_msg
    _last_api_error_ts = time.time()
    _last_api_error_msg = str(msg)[:200]

# -- Redo detection (anti-compulsion guardrail) ──────────────────
# Tracks consecutive re-recordings of similar content.
REDO_SIMILARITY_THRESHOLD = 0.7   # word overlap ratio to count as "same sentence"
REDO_NUDGE_THRESHOLD = 3          # redos before nudge
_redo_buffer = []                 # list of recent output word sets
_redo_count = 0                   # consecutive redo counter
_redo_lock = threading.Lock()
_block_count = 0                  # block suspects detected in last transcription

def check_redo(output_text):
    """Check if this output is a redo of the previous recording.
    Returns redo count (0 = not a redo)."""
    global _redo_count
    with _redo_lock:
        if not output_text or not _redo_buffer:
            _redo_buffer.clear()
            _redo_buffer.append(set(output_text.lower().split()) if output_text else set())
            _redo_count = 0
            return 0
        current_words = set(output_text.lower().split())
        last_words = _redo_buffer[-1]
        if not current_words or not last_words:
            _redo_buffer.clear()
            _redo_buffer.append(current_words)
            _redo_count = 0
            return 0
        # Jaccard similarity
        overlap = len(current_words & last_words) / max(len(current_words | last_words), 1)
        if overlap >= REDO_SIMILARITY_THRESHOLD:
            _redo_count += 1
            _redo_buffer.append(current_words)
            if len(_redo_buffer) > 5:
                _redo_buffer.pop(0)
            return _redo_count
        else:
            _redo_buffer.clear()
            _redo_buffer.append(current_words)
            _redo_count = 0
            return 0


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
_log_lock = threading.Lock()

def log(text, kind="info"):
    global console_id
    with _log_lock:
        console_id += 1
        console_log.append({"id": console_id, "ts": time.time(), "text": text, "kind": kind})
        if len(console_log) > 80:
            console_log.pop(0)
    try:
        print(text)
    except Exception:
        pass

# -- Post-processing for local-LLM chattiness ───────────────────
# Small local models (Llama 3.2 3B, Qwen 2.5 3B, Gemma 2 2B) add preambles
# ("Here's the cleaned sentence:"), markdown bold/emphasis, bullet lists,
# and emojis despite system-prompt instructions to output plain text.
# Any of that pastes into the user's active app. Strip deterministically.
_MD_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_MD_ITAL_RE = re.compile(r'(?<!\*)\*([^*\n]+)\*(?!\*)')
_MD_CODE_RE = re.compile(r'`([^`]+)`')
_MD_HEADER_RE = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_BULLET_RE = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+", flags=re.UNICODE
)
_PREAMBLE_RE = re.compile(
    r"^(here(?:'s| is)?|the cleaned(?:[-\s]up)? (?:sentence|text)|cleaned(?:[-\s]up)?|reconstructed|output|result)[^\n]*[:.]\s*",
    re.IGNORECASE
)


def _postprocess_local_llm(text):
    """Strip small-model chattiness before the output reaches the paste target.
    Takes first non-empty line, removes preamble/markdown/emoji, normalizes
    whitespace. Returns empty string if nothing meaningful remains (caller
    falls back to raw L1 text)."""
    if not text:
        return text
    t = text.strip()
    # First non-empty line is the answer. If the model wrote multiple
    # paragraphs, the rest is commentary.
    lines = [ln for ln in t.split("\n") if ln.strip()]
    if not lines:
        return ""
    t = lines[0]
    # Strip preamble ("Here's the cleaned sentence:")
    t = _PREAMBLE_RE.sub("", t, count=1)
    # Strip surrounding quotes that models love to add
    if len(t) >= 2 and t[0] in '"“\'' and t[-1] in '"”\'':
        t = t[1:-1]
    # Strip markdown formatting
    t = _MD_BOLD_RE.sub(r'\1', t)
    t = _MD_ITAL_RE.sub(r'\1', t)
    t = _MD_CODE_RE.sub(r'\1', t)
    t = _MD_HEADER_RE.sub("", t)
    t = _MD_BULLET_RE.sub("", t)
    # Strip emojis
    t = _EMOJI_RE.sub("", t)
    # Normalize whitespace
    t = re.sub(r'\s{2,}', ' ', t).strip()
    return t


# -- LLM Calls ───────────────────────────────────────────────────
def reconstruct(raw_text, tone, layer, prof, situation=None,
                whisper_low_conf=None, whisper_disagreements=None,
                speech_severity_mod=0.0, paralinguistic_events=None,
                prosodic_context=None, language_code="en"):
    """Layer 2+: Rebuild raw transcription into clean output."""
    # Detect if input contains Cyrillic (bilingual speaker)
    has_cyrillic = any('\u0400' <= c <= '\u04ff' for c in raw_text)
    lang_note = " Speaker is bilingual (English/Russian) and may mix languages." if has_cyrillic else ""

    # Situational aggressiveness — higher stress = more aggressive cleanup
    # speech_severity_mod: dynamic boost from real-time pause/rate analysis (#11)
    sit = situation or current_situation
    severity = SITUATION_SEVERITY.get(sit, 1.0) + speech_severity_mod
    aggression_note = ""
    if severity >= 1.4:
        aggression_note = (
            " Speaker is in a HIGH-STRESS context (phone/presentation/interview). "
            "Expect more disfluencies, heavier avoidance, more filler stacking. "
            "Be MORE aggressive in reconstructing — strip more, trust less of the literal words."
        )
    elif severity >= 1.1:
        aggression_note = (
            " Speaker's speech shows elevated pausing or slow rate. "
            "Apply moderate cleanup — fix grammar, strip fillers, smooth hesitations."
        )
    elif severity <= 0.6:
        aggression_note = (
            " Speaker is in a low-stress context. Expect near-fluent speech. "
            "Be conservative — minor cleanup only."
        )
    # Always include raw speech metrics when available (Layer 2+ benefits from this context)
    if speech_severity_mod > 0:
        aggression_note += f" [Speech metrics: severity_boost={speech_severity_mod:.1f}]"

    # Per-tone instructions: each tone gets specific rules about style,
    # contractions, sentence structure, and how much rewriting is allowed
    TONE_RULES = {
        "formal": (
            "Use complete sentences. No contractions. No colloquialisms or slang. "
            "Proper grammar and punctuation. Do not paraphrase — preserve the speaker's "
            "exact word choices where possible. Only fix disfluencies and grammar errors."
        ),
        "professional": (
            "Clean, clear business language. Contractions acceptable but not preferred. "
            "Fix grammar and strip fillers. Minor rephrasing for clarity is OK, "
            "but do not editorialize or change the speaker's intent."
        ),
        "casual": (
            "Natural spoken rhythm. Contractions OK. Colloquial phrasing OK. "
            "Strip fillers and fix obvious errors, but keep the speaker's natural voice. "
            "Don't make it sound like a formal document."
        ),
        "friend": (
            "Conversational, relaxed. Contractions expected. Sentence fragments OK if natural. "
            "Strip fillers and repetitions but preserve personality and informal expressions. "
            "This should sound like a real person talking, not writing."
        ),
    }
    tone_rule = TONE_RULES.get(tone, TONE_RULES["casual"])

    parts = [
        f"Rebuild this raw voice transcription into clean {tone} text.{lang_note}{aggression_note}",
        ("The transcription was produced by an automatic speech recognition system and may contain "
         "artifacts from speech disfluency including repeated words, repeated syllables, filler sounds, "
         "and silence where the speaker was blocked. When the literal transcription doesn't make "
         "grammatical sense, prioritize semantic intent and grammatical coherence over literal word "
         "sequence. Reconstruct what the speaker most likely intended to say, not what the microphone "
         "literally captured."),
        tone_rule,
        "Strip filler words (including non-English fillers like э, ну, ээ).",
        "Preserve FULL meaning. Do not summarize or add information.",
        "Do NOT censor, sanitize, or soften the speaker's language. Profanity, slang, "
        "harsh words, and strong language must be preserved EXACTLY as spoken. "
        "If the speaker said 'fuck', output 'fuck'. If the speaker said 'steal', output 'steal'. "
        "Do not substitute softer synonyms (e.g. do not change 'steal' to 'borrow'). "
        "Your job is to clean up SPEECH ARTIFACTS, not to edit the speaker's word choices.",
        "Output ONLY the reconstructed text.",
        "Do not include any preamble, explanation, meta-commentary, or notes about what you changed.",
        "Do not use Markdown formatting: no asterisks, no backticks, no bullet points, no headers, no quotation marks around the output.",
        "Do not use emojis or emoticons.",
        "Output exactly one line containing only the reconstructed sentence or paragraph, with no leading or trailing whitespace.",
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

    # -- Whisper confidence signals (L2+, zero additional cost) ──────
    # Data always computed; prompt framing is layer-differentiated:
    # L4 = stutter-clinical ("BLOCK suspects"), L2/L3 = general ASR-aware
    if whisper_low_conf:
        lc_notes = []
        block_notes = []
        for seg in whisper_low_conf[:5]:
            if seg.get("block_suspect"):
                block_notes.append(f"  \"{seg['text']}\" (no_speech_prob={seg['no_speech_prob']})")
            else:
                lc_notes.append(
                    f"  \"{seg['text']}\" (logprob={seg['avg_logprob']}, brown_risk={seg['brown_risk']})"
                )
        if lc_notes:
            if layer >= 4:
                parts.append(
                    "\n⚠ WHISPER UNCERTAINTY — these segments have low decoder confidence "
                    "AND high stuttering risk. They are almost certainly transcription artifacts:\n"
                    + "\n".join(lc_notes)
                    + "\nReconstruct aggressively. Trust semantic context, not the literal words."
                )
            else:
                parts.append(
                    "\n⚠ LOW CONFIDENCE — Whisper's decoder was uncertain about these words:\n"
                    + "\n".join(lc_notes)
                    + "\nThese may be misheard. Use surrounding context to determine what was actually said."
                )
        if block_notes:
            if layer >= 4:
                parts.append(
                    "\n⚠ BLOCK SUSPECTS — Whisper nearly classified these as silence "
                    "(high no_speech_prob). For this speaker, silence before/during a word "
                    "is a BLOCK, not absence of speech. The text here is likely hallucinated "
                    "filler that Whisper invented to fill the gap:\n"
                    + "\n".join(block_notes)
                    + "\nDiscard these words entirely or replace with the word the speaker "
                    "was trying to say (use semantic context from surrounding words)."
                )
            else:
                parts.append(
                    "\n⚠ POSSIBLE HALLUCINATION — Whisper nearly classified these segments as silence "
                    "but produced text anyway. The words here may be fabricated:\n"
                    + "\n".join(block_notes)
                    + "\nEvaluate carefully — if these words don't fit the context, discard them."
                )
    if whisper_disagreements:
        dis_notes = []
        for d in whisper_disagreements[:5]:
            variants = "/".join(set(d["variants"]))
            dis_notes.append(f"  position {d['position']}: [{variants}]")
        parts.append(
            "\n⚠ MULTI-PASS DISAGREEMENT — Whisper produced different words at these positions "
            "across 3 decoding temperatures. Disagreement = uncertain = likely misheard:\n"
            + "\n".join(dis_notes)
            + "\nThe truth is in the semantic context, not any single variant."
        )

    # -- L2/L3 general ASR artifact guidance ───────────────────────
    # Lighter than L4's clinical taxonomy but gives the model awareness
    # of common voice transcription errors so it can fix them intelligently.
    if 2 <= layer <= 3:
        parts.append(
            "\nThe input is a voice transcription and may contain ASR artifacts:"
            "\n- Repeated words or phrases from natural speech hesitation"
            "\n- Filler sounds transcribed as real words (e.g., 'um' → 'come')"
            "\n- Phantom words inserted during pauses in speech"
            "\n- Phonetically similar but semantically wrong words (misheard)"
            "\n- Truncated or garbled words from unclear pronunciation"
            "\nWhen a word is phonetically plausible but doesn't fit the context, "
            "prefer the contextually correct interpretation."
            "\n\nExamples:"
            "\n  IN:  'So um I was going to uh the store to get some, some milk'"
            "\n  OUT: 'I was going to the store to get some milk'"
            "\n  IN:  'Can you send me the, the report by, by Friday'"
            "\n  OUT: 'Can you send me the report by Friday'"
            "\n  IN:  'I think we should, we should probably move the meeting'"
            "\n  OUT: 'I think we should probably move the meeting'"
            "\n  IN:  'The, uh, what's it called, the database needs updating'"
            "\n  OUT: 'The database needs updating'"
        )

    if layer >= 4:
        # Inject per-user phoneme difficulty map from learned onset weights
        # Approximates per-phoneme model adaptation at the cleanup layer
        if _personal_onset_weights:
            ranked = sorted(_personal_onset_weights.items(), key=lambda x: -x[1])
            hard_onsets = [f"/{o}/ ({round(w*100)}%)" for o, w in ranked[:6] if w >= 0.4]
            if hard_onsets:
                parts.append(
                    f"\n⚠ THIS SPEAKER'S HARDEST PHONEMES: {', '.join(hard_onsets)}"
                    "\nWhisper output near these onsets is unreliable — expect hallucinations, "
                    "syllable drops, or phantom word insertions. Trust semantic context over "
                    "literal transcription when words starting with these sounds look garbled."
                )
        # Inject covert avoidance patterns if known
        covert = prof.get("covert_profile", {}).get("avoidance_pairs", {})
        if covert:
            covert_note = []
            for sit, words in list(covert.items())[:3]:
                for word, data in list(words.items())[:3]:
                    subs = data.get("common_substitutes", [])[:2]
                    if subs:
                        covert_note.append(f"'{word}' → {subs} (avoidance of /{data.get('dominant_onset', '?')}/)")
            if covert_note:
                parts.append(
                    "\n⚠ KNOWN COVERT AVOIDANCE: speaker sometimes swaps these words: "
                    + "; ".join(covert_note)
                    + "\nIf you see a synonym where the original word would fit better, "
                    "the original IS what they meant. Reconstruct with the intended word."
                )

        # Whisper confidence injection now at Layer 2+ (above)

        # Language-parameterized L4 block (docs/l4_prompt_engineering_memo.md § 4–5)
        _lang_code = _normalize_lang_code(language_code)
        _lang_name_str = _lang_name(_lang_code)
        _lang_fillers = _get_lang_fillers(_lang_code)
        _lang_natural_repeats = _get_lang_natural_repeats(_lang_code)
        _dialect_note = _get_lang_dialect_avoidance_note(_lang_code)
        _timing_note = _get_lang_syllable_timing_note(_lang_code)

        _l4 = []
        _l4.append(
            f"\nThe speaker has a speech disfluency. Language: {_lang_code.upper()} ({_lang_name_str}). "
            "Raw transcription is evidence of intent, not truth. "
            "Reconstruct the intended message. Preserve FULL meaning."
        )
        if _lang_fillers:
            _l4.append(f"\n\nFILLERS TO STRIP ({_lang_code}): {', '.join(_lang_fillers)}")
        if _lang_natural_repeats:
            _l4.append(
                f"\n\nEMPHATIC PATTERNS — DO NOT STRIP in {_lang_code}: {', '.join(_lang_natural_repeats)}"
                f"\nThese are pragmatically meaningful in {_lang_name_str}, not stuttering."
            )
        _l4.append("\n\nOvert disfluencies — strip and reconstruct:")
        _l4.append(f"\n- Part-word repetitions: {_get_lang_part_word_example(_lang_code)}")
        _l4.append("\n- Whole-word repetitions (NOT matching the emphatic allow-list above)")
        _l4.append(f"\n- Prolongations: {_get_lang_prolongation_example(_lang_code)}")
        _l4.append(f"\n- Epenthetic insertions during blocks: {_get_lang_epenthesis_note(_lang_code)}")
        _l4.append("\n- Blocks: silence or frozen onset before a word (locked articulators)")
        _l4.append("\n- Tremors: lip/jaw quivering during a fixation")
        _l4.append("\n- Secondary behaviors: eye blinks, foot taps, head movements during blocks")
        _l4.append("\n- False starts and restarts")

        _l4.append("\n\nCovert avoidance — recognize as avoidance behavior, not content:")
        _l4.append("\n- Filler clusters before a content word = postponement (see filler list above)")
        _l4.append("\n- Synonym substitution = avoiding a feared word")
        _l4.append("\n- Circumlocution = talking around a feared word")
        _l4.append("\n- Sentence abandonment = dropping thought before feared word ('Oh, never mind')")
        _l4.append("\n- Covert interruption = jumping in while someone talks to mask onset difficulty")
        _l4.append(
            "\n- Mazes: extended filler runs adding no information. DISTINCT from cluttered "
            "rapid speech — do not over-strip if the speaker's speech is globally rapid."
        )
        if _dialect_note:
            _l4.append(f"\n{_dialect_note}")

        _l4.append("\n\nAnticipatory behavior:")
        _l4.append(
            "\n- A pause or silence BEFORE a content word with a hard onset MAY INDICATE anticipatory fear"
        )
        _l4.append(
            "\n- Confidence increases when a filler cluster appears in the preceding 1–3 words "
            "AND the following word begins with a documented hard onset"
        )
        _l4.append("\n- Treat as a block candidate, not certainty")
        if _timing_note:
            _l4.append(f"\n{_timing_note}")

        _l4.append("\n\nWhisper ASR failure modes on disfluent speech:")
        _l4.append("\n- HALLUCINATION DURING BLOCKS: silence → Whisper generates phantom text.")
        _l4.append(
            "\n  Known hallucination strings to discard: 'thank you', 'thanks for watching', "
            "'subscribe', 'like and subscribe', 'transcribed by', 'captions by', 'otter.ai'."
        )
        if _lang_code != "en":
            _l4.append(
                f"\n  In {_lang_name_str} transcripts, English phrases appearing mid-utterance "
                "are likely Whisper hallucinations — discard them."
            )
        _l4.append("\n- SYLLABLE DELETION: repeated syllables collapsed or dropped")
        _l4.append("\n- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar-sounding words")
        _l4.append(f"\n- {_get_lang_epenthesis_corruption_note(_lang_code)}")
        _l4.append("\n- PAUSE HALLUCINATION: long pauses → Whisper generates filler text (see above)")

        _l4.append("\n\n")
        _l4.append(_get_lang_few_shot_examples(_lang_code))

        _l4.append(
            "\n\nDo not mistake disfluency for emphasis — but PRESERVE the emphatic patterns listed above."
            "\nReconstruct within the speaker's established dialect — do not substitute dialectal forms."
            "\nWhen uncertain, prefer conservative cleanup over aggressive rewriting."
        )

        _onset_caveat = _get_lang_onset_caveat(_lang_code)
        if _onset_caveat:
            _l4.append(f"\n{_onset_caveat}")
        if _lang_has_no_onset_research(_lang_code):
            _l4.append(
                f"\n\nONSET NOTE: No published phoneme-difficulty research exists for {_lang_code} "
                "as of April 2026. Do not apply English-derived onset assumptions. Focus on word-level "
                "repetitions, prolongations, filler clusters, and Whisper hallucination strings."
            )

        parts.append("".join(_l4))
        if prof.get("trigger_words"):
            parts.append(f"\nKnown trigger words: {', '.join(prof['trigger_words'])}")
        # Personal phonetic pattern: tell the LLM which sounds this user blocks on
        if _personal_dominant_onsets:
            onset_desc = ", ".join(
                f"/{d['onset']}/ ({d['pct']}%)" for d in _personal_dominant_onsets
            )
            parts.append(
                f"\nThis speaker's personal block pattern: {onset_desc} of triggers. "
                "Words starting with these sounds are HIGH PRIORITY for reconstruction — "
                "expect heavier disfluency on these onsets specifically."
            )
        # Predictive: flag words in this utterance that are phonetically risky
        predicted = predict_triggers_in_text(raw_text, prof.get("trigger_words", []))
        if predicted:
            flagged = [f"{w}({r})" for w, r in predicted[:10]]
            parts.append(f"\nPhonetically predicted high-risk words in this utterance: {', '.join(flagged)}")

    # -- Layer 5: Paralinguistic event context ───────────────────
    # Tell the LLM which segments contain non-speech events so it ignores
    # Whisper hallucinations near those timestamps.
    if paralinguistic_events:
        para_notes = []
        for ev in paralinguistic_events[:8]:
            para_notes.append(
                f"  [{ev['type']}] at {ev['start_s']:.1f}s–{ev['end_s']:.1f}s "
                f"(confidence={ev['confidence']}, HNR={ev.get('hnr_db', '?')}dB)"
            )
        if para_notes:
            parts.append(
                "\n⚠ PARALINGUISTIC EVENTS DETECTED — the following non-speech sounds were "
                "found in the audio. Whisper likely hallucinated words in these windows. "
                "IGNORE or DISCARD any transcribed text that falls within ±1 second of "
                "these timestamps — it is not speech:\n"
                + "\n".join(para_notes)
                + "\nReconstruct using surrounding context only. Do not try to interpret "
                "non-speech sounds as words."
            )

    # -- Layer 5.5: Prosodic bridging ──────────────────────────────
    # Rich per-segment prosodic transcript: F0, energy, rate, pitch direction,
    # speaker state. Gives GPT the acoustic features Whisper destroyed.
    # Validated by: USDM (NeurIPS 2024), SpeechEmotionLlama (Interspeech 2025)
    if prosodic_context:
        parts.append("\n" + prosodic_context)

    # Per-tone temperature: formal/professional = low creativity (stick to the words),
    # casual/friend = higher creativity (natural rewording OK)
    TONE_TEMP = {"formal": 0.1, "professional": 0.15, "casual": 0.35, "friend": 0.4}
    temp = TONE_TEMP.get(tone, 0.3)

    global _last_recon_model
    use_model = MODEL_L4 if layer >= 4 else MODEL
    system_prompt = "\n".join(parts)

    # L4 clinical reconstruction → Anthropic Sonnet 4.6 with extended thinking.
    # The reasoning trace IS the differentiator — for severe stutterers and
    # SLP audit, the model walks through Whisper's confidence signals + the
    # speaker's phoneme map + covert avoidance + Brown risk + prosodic state
    # in its scratchpad before producing the reconstruction. Falcon at L4 is
    # dropped because extended thinking is itself self-validation.
    # Falls through to GPT-4o on Anthropic error or unavailability.
    if layer >= 4 and anthropic_client is not None:
        try:
            msg = anthropic_client.messages.create(
                model=SONNET_THINK_MODEL,
                max_tokens=SONNET_THINK_MAX_TOKENS,
                thinking={"type": "enabled", "budget_tokens": SONNET_THINK_BUDGET},
                system=system_prompt,
                messages=[{"role": "user", "content": raw_text}],
            )
            text_blocks = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
            clean_text = "\n".join(text_blocks).strip()
            if clean_text:
                stats_inc("anthropic_calls")
                _last_recon_model = f"{SONNET_THINK_MODEL} (ext-think)"
                return clean_text
            # Empty Sonnet output — fall through to GPT-4o
        except Exception as e:
            log(f"Sonnet 4.6 ext-think failed ({str(e)[:120]}), falling back to GPT-4o", "warn")

    # L2/L3 cloud reconstruction (and L4 fallback): GPT-4o single-pass.
    stats_inc("api_calls")
    resp = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text}
        ],
        max_tokens=1000,
        temperature=temp
    )
    _last_recon_model = use_model
    return resp.choices[0].message.content.strip()


def falcon_validate(raw_text, clean_text, layer, tone="casual", onset_weights=None, language_code="en"):
    """Binary meaning check. Returns True if meaning preserved.
    Tone-aware: formal tone expands contractions, casual keeps them — Falcon must know
    which changes are expected per tone."""
    tone_note = ""
    if tone == "formal":
        tone_note = (
            " Tone is FORMAL: contractions expanded to full form (don't→do not, I'm→I am) "
            "and colloquialisms replaced with standard English are expected, not meaning changes."
        )
    elif tone == "professional":
        tone_note = " Tone is PROFESSIONAL: light formality adjustments are expected."
    elif tone == "friend":
        tone_note = " Tone is FRIEND: sentence fragments and casual contractions are expected."
    # casual: no extra note needed
    if layer <= 3:
        prompt = (
            "The reconstruction cleans up a voice transcription: removing filler words "
            "(um, uh, like, you know), fixing grammar, and improving clarity. "
            "Filler removal and grammar fixes are expected and acceptable." + tone_note + " "
            "Does the reconstruction preserve the core content and intent? "
            "Answer ONLY 'yes' or 'no'."
        )
    elif layer >= 4:
        # Phonetic guard first, high-level criteria after. Does not re-specify
        # the L4 rules already given to the reconstruction prompt.
        _lc = _normalize_lang_code(language_code)
        if onset_weights:
            _top = ", ".join(
                f"/{o}/" for o, _ in sorted(onset_weights.items(), key=lambda x: -x[1])[:5]
            )
        else:
            _top = "(no personal onset data)"
        _nr = _get_lang_natural_repeats(_lc)
        _nr_str = ", ".join(_nr) if _nr else "none defined"
        prompt = (
            f"Validate a layer-4 speech-disfluency reconstruction. Language: {_lc.upper()}. "
            f"Near the speaker's hardest phonemes ({_top}), the reconstruction MUST NOT "
            "substitute a different-phoneme word — phonetic drift is the primary failure mode. "
            "The reconstruction should also have: "
            "(1) stripped overt disfluencies (part-word repetitions, prolongations, blocks, false starts); "
            f"(2) preserved emphatic patterns that are NOT stuttering: {_nr_str}; "
            "(3) NOT normalized the speaker's dialect or register forms; "
            "(4) discarded Whisper hallucination strings ('thank you', 'subscribe', etc.)."
            + tone_note
            + " Does the reconstruction satisfy all criteria? Answer ONLY 'yes' or 'no'."
        )

    # L4 reconstruction uses Sonnet 4.6 with extended thinking — the reasoning
    # trace IS the validator. A separate yes/no Falcon check after that adds
    # latency without adding signal. Skip Falcon at L4.
    if layer >= 4:
        return True

    # L2/L3 Falcon → Claude Haiku 4.5 (Anthropic) for cross-vendor validation.
    # Different vendor = different blind spots → catches errors that self-eval misses.
    # If Anthropic key isn't configured, fall back to GPT-4o (same vendor as recon).
    if layer in (2, 3) and anthropic_client is not None:
        try:
            msg = anthropic_client.messages.create(
                model=FALCON_HAIKU_MODEL,
                max_tokens=5,
                messages=[{
                    "role": "user",
                    "content": prompt + f"\n\nOriginal: {raw_text}\nReconstruction: {clean_text}",
                }],
            )
            stats_inc("anthropic_calls")
            return "yes" in msg.content[0].text.strip().lower()
        except Exception:
            pass  # fall through to OpenAI on Haiku error

    # L4 Falcon (clinical) → GPT-4o (rich phonetic-rules prompt; keep on the
    # same family that produced the reconstruction so the eval stays consistent
    # with the reconstruction prompt's structure). Also used as L2/L3 fallback
    # when anthropic_client is unavailable.
    stats_inc("api_calls")
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


# -- Disfluency post-filter (rule-based, zero API cost) ────────
# Post-processing yields significant WER reduction on disfluent speech;
# combined with decoder tuning (Whisper prompt parameter), gains compound
# (informed by Stutter-TTS and Mujtaba "Inclusive ASR for Disfluent Speech").

# Common fillers to strip (bilingual EN/RU)
_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}

# Natural English repetitions that should NOT be stripped (Apple ML Research, 2023)
# These are grammatically valid constructions, not disfluencies
NATURAL_REPEATS = {
    "had had", "that that", "is is", "was was", "do do",
    "can can", "no no", "bye bye", "so so", "very very",
    "go go", "now now", "come come", "well well",
    "out out", "boo boo", "ha ha", "ho ho",
    "knock knock", "tsk tsk", "aye aye",
    # Russian
    "да да", "нет нет", "ну ну",
}


# Known Whisper training-data hallucinations. These leak in during silence,
# whispered audio, or low-SNR clips because Whisper's training set included
# YouTube auto-captions with these credits/subscribe-nags.
# Custom patterns (45) + Bag of Hallucinations dataset (1,270) from
# Barański et al. 2025 — "Investigation of Whisper ASR Hallucinations
# Induced by Non-Speech Audio" (https://arxiv.org/abs/2501.11378)
_WHISPER_HALLUCINATIONS = [
    # Custom patterns
    # Prompt leak hallucinations (system prompt fragments leaking into transcription)
    r"transcribe intended words only",
    r"clear,?\s*fluent speech",
    r"not repetitions or filler",
    # Otter.ai / transcription service credits
    r"transcribed by\s+(https?://)?otter\.?ai",
    r"transcription by\s+castingwords",
    r"subtitles?\s+(by|courtesy of)\s+the?\s*amara\.org\s*community",
    r"subtitled by\s+the?\s*amara\.org\s*community",
    r"captions by[^.]{0,30}",
    r"transcript by[^.]{0,30}",
    # YouTube endings
    r"thank you for watching[.!]?",
    r"thanks for watching[.!]?(\s+see you next time)?[.!]?",
    r"thanks for listening[.!]?",
    r"don'?t forget to (like|subscribe)",
    r"(please\s+)?like and subscribe",
    r"like,?\s*comment,?\s*(and\s+)?subscribe",
    r"subscribe to (my|our|the) channel",
    r"click the bell (icon|button)?",
    r"hit the (bell|notification)",
    r"see you (in the )?next (video|episode|time)[.!]?",
    r"leave a comment (below|down)",
    r"check out (our|my) (website|channel|links?)",
    r"follow (us|me) on",
    # Legal / disclaimer boilerplate (leaked today: "please see the complete disclaimer at sites.google.com")
    r"please see the complete disclaimer",
    r"for more information,?\s*visit",
    r"all rights reserved\.?",
    r"copyright\s+\d{4}",
    r"terms (and|&) conditions apply",
    r"terms of service",
    r"this content is (licensed|provided)",
    r"visit (us|our website) at",
    r"powered by[^.]{0,30}",
    # Podcast / sponsor credits
    r"sponsored by[^.]{0,40}",
    r"brought to you by[^.]{0,40}",
    r"this (episode|video|content) is",
    r"available on all (platforms|streaming)",
    # Music / sound markers
    r"♪+\s*♪*",
    r"\[music\]",
    r"\[applause\]",
    r"\[silence\]",
    r"\[no audio\]",
    r"\[laughter\]",
    # Chatbot refusal leaks (safety net — catches LLM reconstruction output that's a refusal, not speech)
    r"^I'?m sorry,?\s*I (can'?t|cannot|don'?t|didn'?t)\s+(assist|help|catch|understand)",
    r"^(sorry,?\s+)?I didn'?t catch that",
    r"^could you (please\s+)?(clarify|repeat|rephrase|say that again)",
    r"^I'?m not sure what you meant",
    r"^please (clarify|provide more context)",
    # Minimal hallucinations (silence → single word)
    r"^\s*thank you\.\s*$",
    r"^\s*you\.\s*$",
    r"^\s*\.\s*$",
    # Stray URLs appearing out of nowhere (hallucinated from training data)
    r"(?<!\S)https?://\S+(?!\S)",
    # BoH dataset REMOVED — Barański et al. 2025 patterns included single common
    # words ('the', 'you', 'so', 'i', 'a', 'is', 'no', 'yes', 'what', 'yeah',
    # 'okay', 'hello', etc.) that matched real speech and destroyed transcriptions.
    # The 47 custom regex patterns above are sufficient.
]
_WHISPER_HALLUCINATION_RE = re.compile(
    "|".join(f"({p})" for p in _WHISPER_HALLUCINATIONS),
    re.IGNORECASE
)

def strip_whisper_hallucinations(text):
    """Remove well-known Whisper training-data hallucinations (zero cost).
    Returns empty string if the entire text WAS a hallucination — the whole
    utterance is garbage, nothing should be pasted."""
    if not text:
        return text
    cleaned = _WHISPER_HALLUCINATION_RE.sub("", text).strip()
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned  # may be empty — that's correct if entire output was hallucination


def strip_disfluencies(text):
    """Remove obvious disfluency artifacts from transcription.

    Handles:
      1. Word repetitions: "I I I want" → "I want"
      2. Part-word/stutter fragments: "p- p- pop" → "pop"
      3. Common filler words: "um", "uh", "er" (EN + RU)
      4. Phrase repetitions: "I want I want to go" → "I want to go"

    Designed for L1 (transcribe-only) post-processing and
    L2+ pre-cleaning before GPT reconstruction.
    """
    if not text or not text.strip():
        return text

    # Step 1: Remove stutter fragments (hyphenated false starts)
    # "p- p- pop" → "pop",  "be- be- become" → "become"
    cleaned = re.sub(r'(\b\w+)-\s+(?:\1-\s+)*', '', text, flags=re.IGNORECASE)

    # Step 2: Remove consecutive word repetitions
    # "I I I want" → "I want",  "the the dog" → "the dog"
    # Exception: naturally repeating English constructions (ha ha, bye bye, etc.)
    def _dedup_word(m):
        phrase = f"{m.group(1)} {m.group(1)}".lower()
        if phrase in NATURAL_REPEATS:
            return m.group(0)  # Don't strip — natural repetition
        return m.group(1)
    # Require 3+ repetitions (2+ is often emphasis: "no no", "go go", "please please")
    cleaned = re.sub(r'\b(\w+)(?:\s+\1){2,}\b', _dedup_word, cleaned, flags=re.IGNORECASE)

    # Step 3: Remove phrase repetitions (2-3 word phrases repeated)
    # "I want I want to go" → "I want to go"
    # Exception: naturally repeating phrases in NATURAL_REPEATS
    def _dedup_phrase(m):
        if m.group(1).lower() in NATURAL_REPEATS:
            return m.group(0)  # Don't strip — natural repetition
        return m.group(1)
    cleaned = re.sub(
        r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', _dedup_phrase, cleaned, flags=re.IGNORECASE
    )

    # Step 4: Strip standalone filler words (preserve if part of real content)
    words = cleaned.split()
    filtered = []
    for i, w in enumerate(words):
        w_lower = w.lower().rstrip('.,!?;:')
        if w_lower in _STRIP_FILLERS:
            # Keep filler only if it's the entire utterance
            if len(words) == 1:
                filtered.append(w)
            # Otherwise skip it
            continue
        filtered.append(w)

    result = " ".join(filtered).strip()
    # Collapse multiple spaces
    result = re.sub(r'\s{2,}', ' ', result)
    # Don't return empty string — fall back to original
    return result if result else text


def apply_profile_corrections(text, prof):
    """Apply known corrections from profile to transcription (zero API cost).

    Used at L1 to fix known Whisper misrecognitions without GPT reconstruction.
    Profile corrections are learned over time (e.g., "Duncan" → "Dankeschön",
    "Web3Forms" → "WordPress"). At L2+ these are fed to GPT; at L1 we apply
    them directly via regex word-boundary replacement.
    """
    corrections = prof.get("corrections", {})
    if not corrections or not text:
        return text
    result = text
    for wrong, right in corrections.items():
        pattern = re.compile(r'\b' + re.escape(wrong) + r'\b', re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(right, result)
            log(f"L1 correction: \"{wrong}\" → \"{right}\"", "info")
    return result


def strip_block_hallucinations(text, low_conf_segments):
    """Strip Whisper-hallucinated text from block-suspect segments (zero API cost).

    Two sources of Whisper hallucination both get removed:
      1. Block suspects: silence (stuttering block) where Whisper invents "Thank you",
         "Okay", etc. — short filler phrases (≤3 words).
      2. Repetition loops: compression_ratio > 2.4 means Whisper's decoder got stuck
         producing "bad bad bad..." or "Thank you Thank you Thank you..." garbage.
         Removed regardless of length since the whole segment is corrupt.

    Uses confidence metadata already in the Whisper verbose_json response — no extra
    API cost.
    """
    if not low_conf_segments or not text:
        return text
    result = text
    for seg in low_conf_segments:
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue
        # Repetition loops: always strip (whole segment is Whisper garbage)
        if seg.get("repetition_loop"):
            before = result
            result = result.replace(seg_text, "")
            if result != before:
                log(f"Strip repetition loop: \"{seg_text[:60]}...\" (compression={seg['compression_ratio']})", "info")
        # Block suspects: strip short phrases only
        elif seg.get("block_suspect") and len(seg_text.split()) <= 3:
            before = result
            result = result.replace(seg_text, "")
            if result != before:
                log(f"Block strip: \"{seg_text}\" (no_speech_prob={seg['no_speech_prob']})", "info")
    result = re.sub(r'\s{2,}', ' ', result).strip()
    return result if result else text


def count_disfluencies(raw_text):
    """Count disfluency events by type in raw transcription. Zero-cost."""
    if not raw_text:
        return {}
    counts = {}
    # Sound/syllable repetitions: "b-b-buy", "co-co-come"
    n = len(re.findall(r'(\b\w+)-\s+(?:\1-\s+)*', raw_text, re.IGNORECASE))
    if n: counts["sound_rep"] = n
    # Word repetitions: "I I I want"
    n = len(re.findall(r'\b(\w+)(?:\s+\1)+\b', raw_text, re.IGNORECASE))
    if n: counts["word_rep"] = n
    # Phrase repetitions (stutter): "I want I want to go" (2-word, repeated once)
    n = len(re.findall(r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', raw_text, re.IGNORECASE))
    if n: counts["phrase_rep"] = n
    # Fillers
    words = raw_text.lower().split()
    n = sum(1 for w in words if w.rstrip('.,!?;:') in _STRIP_FILLERS)
    if n: counts["filler"] = n
    # Prolongations (stretched sounds transcribed by Whisper)
    n = len(re.findall(r'\b(\w)\1{3,}\w*\b', raw_text, re.IGNORECASE))
    if n: counts["prolongation"] = n
    # Compulsive loops: phrase repeated 3+ times (distinct from stutter phrase_rep at 2x)
    loop_matches = detect_ocd_loops(raw_text)
    if loop_matches:
        counts["loop_compulsion"] = len(loop_matches)
    counts["total"] = sum(counts.values())
    return counts


def detect_ocd_loops(text):
    """Detect compulsive phrase loops (3+ repetitions of a 2-4 word phrase).
    Returns list of {phrase, count} dicts for profile tracking.

    Uses an O(n) sliding-window n-gram approach instead of the original regex,
    which had nested quantifiers that could backtrack catastrophically on long input."""
    if not text:
        return []
    # Normalize: lowercase, strip punctuation from words
    words = [w.strip('.,!?;:"\'-') for w in text.lower().split()]
    words = [w for w in words if w]
    if len(words) < 6:  # need at least 3 repetitions of a 2-word phrase
        return []

    seen = {}  # (ngram_tuple) -> count of consecutive runs
    loops = []

    # Check phrase lengths 2, 3, 4
    for n in (2, 3, 4):
        if len(words) < n * 3:
            continue
        # Build list of n-grams
        ngrams = [tuple(words[i:i+n]) for i in range(len(words) - n + 1)]
        # Scan for consecutive repetitions
        i = 0
        while i < len(ngrams):
            gram = ngrams[i]
            count = 1
            j = i + n  # next n-gram that could be a repeat starts n words later
            while j < len(ngrams) and ngrams[j] == gram:
                count += 1
                j += n
            if count >= 3:
                phrase = " ".join(gram)
                if phrase not in seen or seen[phrase] < count:
                    seen[phrase] = count
            i += 1

    for phrase, count in seen.items():
        loops.append({"phrase": phrase, "count": count})
    return loops


# -- Exposure difficulty scoring ───────────────────────────────
# Combines phonetic risk, situational severity, and disfluency density
# into a single 0.0-1.0 score per utterance. Enables therapy-aware
# tracking: "you used high-risk word X in 4/5 attempts this week."

def compute_exposure_difficulty(raw_text, situation, disf_counts, prof):
    """Score how challenging this utterance was for the speaker.
    Returns dict with overall score (0.0-1.0) and component breakdown."""
    if not raw_text:
        return {"score": 0.0, "components": {}}

    words = re.findall(r'\b\w+\b', raw_text.lower())
    if not words:
        return {"score": 0.0, "components": {}}

    # Component 1: Brown's 4-feature risk (onset + content/function + position + length)
    n = len(words)
    risks = [predict_phonetic_risk(w, sentence_position=i, sentence_length=n)
             for i, w in enumerate(words) if w not in FUNCTION_WORDS and len(w) > 1]
    avg_risk = sum(risks) / len(risks) if risks else 0.2
    high_risk_count = sum(1 for r in risks if r >= 0.6)

    # Component 2: Situational pressure (resolve legacy aliases)
    situation = _SITUATION_ALIASES.get(situation, situation) if situation else "default"
    sit_severity = SITUATION_SEVERITY.get(situation or "default", 1.0)
    sit_score = min((sit_severity - 0.6) / 1.2, 1.0)  # normalize 0.6-1.8 → 0.0-1.0

    # Component 3: Disfluency density (events per word)
    total_disf = disf_counts.get("total", 0) if disf_counts else 0
    disf_density = min(total_disf / max(len(words), 1), 1.0)

    # Component 4: Trigger word usage (did user use known triggers?)
    known_triggers = {t.lower() for t in prof.get("trigger_words", [])}
    triggers_used = [w for w in words if w in known_triggers]
    trigger_ratio = len(triggers_used) / max(len(words), 1)

    # Weighted composite: phonetic risk most important, then situation
    score = (
        avg_risk * 0.35 +
        sit_score * 0.25 +
        disf_density * 0.20 +
        trigger_ratio * 0.20
    )
    score = round(min(score, 1.0), 3)

    # Difficulty band
    if score < 0.2: band = "low"
    elif score < 0.4: band = "moderate"
    elif score < 0.6: band = "high"
    else: band = "very_high"

    return {
        "score": score,
        "band": band,
        "components": {
            "phonetic_risk": round(avg_risk, 3),
            "high_risk_words": high_risk_count,
            "situation_pressure": round(sit_score, 3),
            "disfluency_density": round(disf_density, 3),
            "trigger_words_used": triggers_used[:10],
            "trigger_ratio": round(trigger_ratio, 3)
        }
    }


# -- Editorial distance (clinical vs functional gap) ──────────
# Measures how much reconstruction was needed: large distance = more
# disfluent speech. Tracking this over time shows objective improvement.

def compute_editorial_distance(raw_text, clean_text):
    """Normalized edit distance between raw and clean text.
    Returns 0.0 (identical) to 1.0 (completely rewritten)."""
    if not raw_text or not clean_text:
        return 0.0
    if raw_text == clean_text:
        return 0.0
    raw_words = raw_text.lower().split()
    clean_words = clean_text.lower().split()
    max_len = max(len(raw_words), len(clean_words))
    if max_len == 0:
        return 0.0
    # Levenshtein on word tokens (not characters — more meaningful for speech)
    m, n = len(raw_words), len(clean_words)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            temp = dp[j]
            if raw_words[i-1] == clean_words[j-1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j], dp[j-1], prev)
            prev = temp
    return round(dp[n] / max_len, 3)


# -- Script Prep (pre-speech word substitution, Ghai & Mueller ASSETS '21)
def prep_text(text, prof):
    """Analyze text the user is about to speak. Flag high-risk words and
    suggest phonetically safer synonyms. Returns list of flagged words
    with alternatives."""
    if not text or not text.strip():
        return {"words": [], "flagged": []}

    triggers = prof.get("trigger_words", [])
    trigger_set = {t.lower() for t in triggers}
    # Score every word using Brown's 4-feature model (onset + content/function + position + length)
    words = re.findall(r'\b\w+\b', text)
    n = len(words)
    scored = []
    for i, w in enumerate(words):
        risk = predict_phonetic_risk(w, sentence_position=i, sentence_length=n)
        # Exact match on known triggers = max risk
        if w.lower() in trigger_set:
            risk = 1.0
        # Boost for onset match with known triggers
        elif any(w.lower()[:2] == t.lower()[:2] for t in triggers if len(t) >= 2):
            risk = min(risk + 0.2, 1.0)
        scored.append({"word": w, "risk": round(risk, 2)})

    flagged = [s for s in scored if s["risk"] >= 0.6]
    if not flagged:
        return {"words": scored, "flagged": []}

    # Build onset avoidance list from personal patterns
    avoid_onsets = []
    if _personal_onset_weights:
        avoid_onsets = sorted(_personal_onset_weights.keys(),
                              key=lambda k: _personal_onset_weights[k], reverse=True)[:5]

    flagged_words = list(dict.fromkeys(s["word"] for s in flagged))  # unique, order-preserved
    onset_note = f"\nOnsets this speaker struggles with: {', '.join(avoid_onsets)}" if avoid_onsets else ""

    stats_inc("api_calls")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are a speech preparation assistant for a person who stutters. "
                    "For each word provided, suggest 2-3 alternative words or short phrases that:\n"
                    "1. Preserve the same meaning in context\n"
                    "2. Are phonetically easier — prefer words starting with vowels, "
                    "continuants (/l/, /m/, /n/, /r/, /w/, /h/), or soft onsets\n"
                    "3. AVOID words starting with these sounds: "
                    f"{', '.join(avoid_onsets) if avoid_onsets else 'stop plosives and consonant clusters'}\n"
                    "4. Sound natural — not clinical or obscure\n"
                    f"{onset_note}\n\n"
                    "Return ONLY valid JSON: {\"suggestions\": {\"word1\": [\"alt1\", \"alt2\"], ...}}\n"
                    "If no good alternative exists, return an empty array for that word."
                )},
                {"role": "user", "content": (
                    f"Context sentence: {text}\n\n"
                    f"Words to find alternatives for: {', '.join(flagged_words[:15])}"
                )}
            ],
            max_tokens=500,
            temperature=0.4
        )
        result_text = resp.choices[0].message.content.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        suggestions = json.loads(result_text).get("suggestions", {})
    except Exception as e:
        log(f"Prep synonyms failed: {e}", "error")
        suggestions = {}

    # Merge suggestions into flagged words
    for item in flagged:
        item["alternatives"] = suggestions.get(item["word"], [])

    # Store prep text for covert avoidance comparison with actual speech
    set_last_prep(text)

    return {"words": scored, "flagged": flagged}


# -- Covert Stuttering Detection (semantic drift tracking) ─────
# Tracks word substitutions between Script Prep intended text and actual speech.
# When a user consistently replaces high-risk words with "safer" synonyms,
# that's covert avoidance — invisible to every other system.
# Buffer: last Script Prep text (cleared after use or after 5 min timeout)
_last_prep_text = None
_last_prep_ts = 0.0
_PREP_EXPIRY_SEC = 300  # 5 minutes — prep text older than this is stale
_prep_lock = threading.Lock()


def set_last_prep(text):
    """Store the most recent Script Prep input for covert avoidance comparison."""
    global _last_prep_text, _last_prep_ts
    with _prep_lock:
        _last_prep_text = text.strip() if text else None
        _last_prep_ts = time.time()


def detect_covert_avoidance(actual_text, prof):
    """Compare actual speech against last Script Prep text to detect covert avoidance.
    Returns list of avoidance pairs: [{intended: word, said: word, onset: str}]
    Returns empty list if no prep text is available or it's expired."""
    global _last_prep_text
    # Snapshot prep text under lock to avoid races with set_last_prep()
    with _prep_lock:
        prep_snapshot = _last_prep_text
        prep_ts_snapshot = _last_prep_ts
    if not prep_snapshot or not actual_text:
        return []
    # Check expiry
    if time.time() - prep_ts_snapshot > _PREP_EXPIRY_SEC:
        with _prep_lock:
            _last_prep_text = None
        return []

    prep_words = [w.lower() for w in re.findall(r'\b\w+\b', prep_snapshot)]
    actual_words = [w.lower() for w in re.findall(r'\b\w+\b', actual_text)]
    if not prep_words or not actual_words:
        return []

    # Build content-word sets (skip function words — they swap freely)
    prep_content = [w for w in prep_words if w not in FUNCTION_WORDS and len(w) > 2]
    actual_content = set(actual_words)

    # Find words that are in prep but NOT in actual speech
    missing = [w for w in prep_content if w not in actual_content]
    if not missing:
        with _prep_lock:
            _last_prep_text = None  # consumed
        return []

    # For each missing word, check if something semantically close appeared instead
    # Heuristic: a word at roughly the same position in the sentence that shares context
    avoidance_pairs = []
    for missed_word in missing:
        risk = predict_phonetic_risk(missed_word)
        if risk < 0.5:
            continue  # low-risk word missing → probably natural rephrasing, not avoidance
        onset = _extract_onset(missed_word)
        # Check if a word at a similar position in actual speech could be a substitute
        # (not same onset, similar sentence role)
        try:
            prep_idx = prep_words.index(missed_word)
        except ValueError:
            continue
        # Look at +/-2 positions in actual text
        window_start = max(0, prep_idx - 2)
        window_end = min(len(actual_words), prep_idx + 3)
        for j in range(window_start, window_end):
            candidate = actual_words[j]
            if candidate in FUNCTION_WORDS or candidate == missed_word:
                continue
            cand_onset = _extract_onset(candidate)
            # Avoidance signal: high-risk word replaced by word with DIFFERENT onset
            if onset and cand_onset != onset and candidate not in prep_content:
                avoidance_pairs.append({
                    "intended": missed_word,
                    "said": candidate,
                    "onset_avoided": onset,
                    "risk_score": round(risk, 2)
                })
                break  # one substitute per missing word

    with _prep_lock:
        _last_prep_text = None  # consumed after comparison
    return avoidance_pairs


def update_covert_profile(prof, avoidance_pairs, situation):
    """Store detected covert avoidance patterns in the user's profile."""
    if not avoidance_pairs:
        return
    covert = prof.setdefault("covert_profile", {"avoidance_pairs": {}})
    pairs = covert.setdefault("avoidance_pairs", {})
    sit = situation or "default"
    sit_data = pairs.setdefault(sit, {})
    now = datetime.now().isoformat()

    for pair in avoidance_pairs:
        word = pair["intended"]
        entry = sit_data.setdefault(word, {
            "avoided_count": 0,
            "used_count": 0,
            "common_substitutes": [],
            "dominant_onset": pair["onset_avoided"],
            "last_seen": now
        })
        entry["avoided_count"] += 1
        entry["last_seen"] = now
        # Track substitute words (keep top 5)
        subs = entry.setdefault("common_substitutes", [])
        if pair["said"] not in subs:
            subs.append(pair["said"])
        if len(subs) > 5:
            entry["common_substitutes"] = subs[-5:]

    # Also count uses when prep word IS used (called separately in pipeline)
    # Cap at 30 tracked words per situation
    if len(sit_data) > 30:
        sorted_items = sorted(sit_data.items(), key=lambda x: x[1]["avoided_count"], reverse=True)
        covert["avoidance_pairs"][sit] = dict(sorted_items[:30])

    save_profile(prof)


# -- Substitution Fingerprinting (#10) ────────────────────────────
# Cross-session aggregate of covert avoidance patterns.
# Computes: avoidance_index (single number), onset heat map,
# situation-specific avoidance rates, and drift detection.

def compute_substitution_fingerprint(prof):
    """Build a cross-session substitution fingerprint from accumulated covert_profile.

    Returns:
      avoidance_index: float 0-1 (0=no avoidance, 1=heavy systematic avoidance)
      onset_heat: dict {onset: avoidance_count} — which sounds get avoided most
      situation_breakdown: dict {situation: {total_avoided, top_word, onset}}
      drift: list of recently emerging avoidance patterns (last 7 days)
      top_substitutions: list of [{word, substitutes, onset, count}] top 10
    """
    covert = prof.get("covert_profile", {})
    pairs = covert.get("avoidance_pairs", {})
    if not pairs:
        return {"avoidance_index": 0.0, "onset_heat": {}, "situation_breakdown": {},
                "drift": [], "top_substitutions": []}

    # Flatten all avoidance data across situations
    onset_heat = {}
    all_words = {}  # word → {total_avoided, substitutes, onset, situations}
    situation_breakdown = {}
    now = datetime.now()

    for situation, words in pairs.items():
        sit_total = 0
        sit_top = None
        sit_max = 0

        for word, data in words.items():
            count = data.get("avoided_count", 0)
            onset = data.get("dominant_onset", "")
            subs = data.get("common_substitutes", [])
            last_seen = data.get("last_seen", "")

            # Onset heat map
            if onset:
                onset_heat[onset] = onset_heat.get(onset, 0) + count

            # Per-word aggregate
            if word not in all_words:
                all_words[word] = {"total_avoided": 0, "substitutes": set(),
                                   "onset": onset, "situations": set(), "last_seen": ""}
            all_words[word]["total_avoided"] += count
            all_words[word]["substitutes"].update(subs)
            all_words[word]["situations"].add(situation)
            if last_seen > all_words[word]["last_seen"]:
                all_words[word]["last_seen"] = last_seen

            sit_total += count
            if count > sit_max:
                sit_max = count
                sit_top = word

        situation_breakdown[situation] = {
            "total_avoided": sit_total,
            "top_word": sit_top,
            "top_onset": all_words[sit_top]["onset"] if sit_top and sit_top in all_words else "",
        }

    # Top substitutions (sorted by total avoidance count)
    top_subs = sorted(all_words.items(), key=lambda x: x[1]["total_avoided"], reverse=True)[:10]
    top_substitutions = [
        {"word": w, "substitutes": list(d["substitutes"]), "onset": d["onset"],
         "count": d["total_avoided"], "situations": list(d["situations"])}
        for w, d in top_subs
    ]

    # Drift: words seen in last 7 days that weren't seen before
    from datetime import timedelta as _td
    seven_days_ago = (now - _td(days=7)).isoformat()
    drift = [
        {"word": w, "onset": d["onset"], "count": d["total_avoided"]}
        for w, d in all_words.items()
        if d["last_seen"] >= seven_days_ago and d["total_avoided"] <= 3
    ]

    # Avoidance index: normalize total avoided count against session count
    total_avoided = sum(d["total_avoided"] for d in all_words.values())
    session_count = max(stats.get("sessions", 1), 1)
    # Avoidance per session, capped at 1.0
    # Baseline: 0-0.5 avoidances/session = low, 0.5-1.5 = moderate, >1.5 = heavy
    avoidance_rate = total_avoided / session_count
    avoidance_index = min(1.0, avoidance_rate / 2.0)  # scale: 2+ avoided/session = 1.0

    return {
        "avoidance_index": round(avoidance_index, 3),
        "onset_heat": dict(sorted(onset_heat.items(), key=lambda x: -x[1])),
        "situation_breakdown": situation_breakdown,
        "drift": drift[:10],
        "top_substitutions": top_substitutions,
    }


# -- Auto-Learn ──────────────────────────────────────────────────
LEARN_EVERY = 3  # run learner every N sessions (Layer 3+)
DECAY_EVERY = 30             # run decay sweep every N sessions
DECAY_STALE_SESSIONS = 100   # corrections unused for this many sessions → demote to candidate
DECAY_DEAD_SESSIONS = 200    # candidates not re-seen for this many sessions → prune entirely
_learn_counter = 0
_decay_counter = 0
learn_events = []  # [{ts, type, value}, ...]
_learn_lock = threading.Lock()
learn_status = {"last_run": None, "total_learned": 0, "next_in": LEARN_EVERY}


def _learn_event(entry):
    """Thread-safe append to learn_events with cap at 50."""
    with _learn_lock:
        learn_events.append(entry)
        if len(learn_events) > 50:
            learn_events[:] = learn_events[-50:]


def _learn_events_snapshot():
    """Thread-safe copy of learn_events for reading."""
    with _learn_lock:
        return list(learn_events)

def learn_from_sessions(prof):
    """Analyze recent raw→output pairs and extract patterns."""
    recent = db_get_sessions(limit=LEARN_EVERY * 3)  # fetch recent, filter below
    recent = [s for s in recent if s.get("layer", 1) >= 2 and s.get("raw") != s.get("out")]
    recent = recent[:LEARN_EVERY]  # already newest-first from db_get_sessions
    if not recent:
        return

    pairs = "\n".join(
        f"Raw: {s['raw']}\nOut: {s['out']}" for s in recent
    )

    stats_inc("api_calls")
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

    # Corrections → candidates → promote (vote-based)
    existing_corr = {k.lower() for k in prof.get("corrections", {})}
    cand_corr = prof.setdefault("candidate_corrections", {})
    for wrong, right in learnings.get("corrections", {}).items():
        wrong = _norm_str(wrong)
        right = _norm_str(right)
        if not wrong or not right:
            continue
        key = wrong.lower()
        if key in existing_corr:
            continue
        if key not in cand_corr:
            cand_corr[key] = {"votes": {}, "total": 0}
        entry = cand_corr[key]
        entry["votes"][right] = entry["votes"].get(right, 0) + 1
        entry["total"] += 1
        if entry["total"] >= LEARN_PROMOTION_THRESHOLD:
            ranked = sorted(entry["votes"].items(), key=lambda x: x[1], reverse=True)
            if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
                _learn_event({"ts": now, "type": "candidate", "value": f"{wrong}: tie ({entry['total']} votes), held"})
                log(f"Candidate tie: \"{wrong}\" — not promoted", "info")
            else:
                winner = ranked[0][0]
                if len(prof.get("corrections", {})) < MAX_PROFILE_ITEMS:
                    prof.setdefault("corrections", {})[wrong] = winner
                del cand_corr[key]
                _learn_event({"ts": now, "type": "correction", "value": f"{wrong} → {winner}"})
                log(f"Promoted: \"{wrong}\" → \"{winner}\"", "info")
                promoted += 1
        else:
            _learn_event({"ts": now, "type": "candidate", "value": f"{wrong} → {right} ({entry['total']}/{LEARN_PROMOTION_THRESHOLD})"})

    # Fillers → candidates → promote
    existing_fillers = {f.lower() for f in prof.get("filler_words", [])}
    cand_fill = prof.setdefault("candidate_fillers", {})
    for filler in learnings.get("fillers", []):
        filler = _norm_str(filler)
        if not filler:
            continue
        key = filler.lower()
        if key in existing_fillers:
            continue
        cand_fill[key] = cand_fill.get(key, 0) + 1
        if cand_fill[key] >= LEARN_PROMOTION_THRESHOLD:
            if len(prof.get("filler_words", [])) < MAX_PROFILE_ITEMS:
                prof.setdefault("filler_words", []).append(key)
            del cand_fill[key]
            _learn_event({"ts": now, "type": "filler", "value": key})
            log(f"Promoted filler: \"{filler}\"", "info")
            promoted += 1
        else:
            _learn_event({"ts": now, "type": "candidate", "value": f"filler: {key} ({cand_fill[key]}/{LEARN_PROMOTION_THRESHOLD})"})

    # Vocabulary → candidates → promote
    existing_vocab = {v.lower() for v in prof.get("vocabulary", [])}
    cand_vocab = prof.setdefault("candidate_vocabulary", {})
    for term in learnings.get("vocabulary", []):
        term = _norm_str(term)
        if not term:
            continue
        key = term.lower()
        if key in existing_vocab:
            continue
        cand_vocab[key] = cand_vocab.get(key, 0) + 1
        if cand_vocab[key] >= LEARN_PROMOTION_THRESHOLD:
            if len(prof.get("vocabulary", [])) < MAX_PROFILE_ITEMS:
                prof.setdefault("vocabulary", []).append(term)
            del cand_vocab[key]
            _learn_event({"ts": now, "type": "vocab", "value": term})
            log(f"Promoted vocab: \"{term}\"", "info")
            promoted += 1
        else:
            _learn_event({"ts": now, "type": "candidate", "value": f"vocab: {term} ({cand_vocab[key]}/{LEARN_PROMOTION_THRESHOLD})"})

    learn_status["last_run"] = now
    if promoted:
        learn_status["total_learned"] += promoted
    else:
        log("Learn: no promotions this cycle", "info")
    save_profile(prof)  # always save — candidate counts changed


# -- Profile Decay (evidence-based staleness pruning) ─────────────
# The reviewer's valid criticism: promoted corrections live forever.
# If you learn "Duncan" → "Dankeschön" at Job A, then move to Job B where
# Duncan is a real name, the stale correction corrupts every output.
#
# Fix: track last_relevant_session for each correction/filler/vocab.
# "Relevant" = the trigger word appeared in raw text (the mapping was
# available to fire). Decay sweep runs every DECAY_EVERY sessions:
#   - Corrections not relevant for DECAY_STALE_SESSIONS → demoted to candidate
#   - Candidates not re-earned for DECAY_DEAD_SESSIONS → pruned
#   - Same logic for fillers and vocabulary

def track_profile_relevance(prof, raw_text):
    """Stamp corrections/fillers/vocab that were relevant to this session.
    Called every session. Updates last_relevant_session counters.

    'Relevant' means the trigger word (correction key, filler, or vocab term)
    appeared in the raw transcription — i.e., the profile entry could have
    fired during reconstruction."""
    session_n = db_session_count()
    raw_lower = raw_text.lower()
    raw_words = set(re.findall(r'\b\w+\b', raw_lower))

    relevance = prof.setdefault("_relevance", {
        "corrections": {},  # key → last_relevant_session
        "fillers": {},
        "vocabulary": {},
    })

    # Corrections: key is the "wrong" word — if it appears in raw, the mapping was relevant
    for key in prof.get("corrections", {}):
        if key.lower() in raw_words:
            relevance["corrections"][key.lower()] = session_n

    # Fillers: if the filler appeared in raw text, it was relevant
    for filler in prof.get("filler_words", []):
        if filler.lower() in raw_words:
            relevance["fillers"][filler.lower()] = session_n

    # Vocabulary: if the term appeared in raw or output, it was relevant
    for term in prof.get("vocabulary", []):
        if term.lower() in raw_words:
            relevance["vocabulary"][term.lower()] = session_n


def decay_stale_profile_entries(prof):
    """Sweep profile for stale entries. Demote corrections → candidates,
    prune dead candidates. Run every DECAY_EVERY sessions.

    Returns count of demoted + pruned entries."""
    session_n = db_session_count()
    relevance = prof.get("_relevance", {})
    now = datetime.now().isoformat()
    demoted = 0
    pruned = 0

    # --- Corrections: demote stale entries back to candidates ---
    corrections = prof.get("corrections", {})
    corr_relevance = relevance.get("corrections", {})
    stale_keys = []
    for key in list(corrections.keys()):
        last_relevant = corr_relevance.get(key.lower(), 0)
        if last_relevant == 0:
            # Never tracked (pre-decay era) — start tracking from now, don't demote yet
            corr_relevance[key.lower()] = session_n
            continue
        if session_n - last_relevant > DECAY_STALE_SESSIONS:
            stale_keys.append(key)

    cand_corr = prof.setdefault("candidate_corrections", {})
    for key in stale_keys:
        value = corrections.pop(key)
        # Demote: put back as candidate with 1 vote (has to re-earn promotion)
        cand_corr[key.lower()] = {
            "votes": {value: 1},
            "total": 1,
            "demoted_at": session_n,
        }
        _learn_event({"ts": now, "type": "decay", "value": f"demoted: {key} → {value} (stale {DECAY_STALE_SESSIONS}+ sessions)"})
        log(f"Decay: demoted correction \"{key}\" → \"{value}\" (unused {DECAY_STALE_SESSIONS}+ sessions)", "info")
        demoted += 1

    # --- Candidates: prune entries that were demoted and never re-earned ---
    for key in list(cand_corr.keys()):
        entry = cand_corr[key]
        demoted_at = entry.get("demoted_at", 0)
        if demoted_at > 0 and session_n - demoted_at > DECAY_DEAD_SESSIONS:
            del cand_corr[key]
            _learn_event({"ts": now, "type": "decay", "value": f"pruned candidate: {key}"})
            log(f"Decay: pruned dead candidate \"{key}\"", "info")
            pruned += 1

    # --- Fillers: demote stale fillers ---
    fillers = prof.get("filler_words", [])
    filler_relevance = relevance.get("fillers", {})
    # Protect bilingual base fillers from decay (they're structural, not learned)
    protected = set()
    for lang_fillers in KNOWN_FILLERS.values():
        protected.update(f.lower() for f in lang_fillers)

    stale_fillers = []
    for filler in fillers:
        if filler.lower() in protected:
            continue  # never decay base fillers
        last_relevant = filler_relevance.get(filler.lower(), 0)
        if last_relevant == 0:
            filler_relevance[filler.lower()] = session_n
            continue
        if session_n - last_relevant > DECAY_STALE_SESSIONS:
            stale_fillers.append(filler)

    for filler in stale_fillers:
        fillers.remove(filler)
        _learn_event({"ts": now, "type": "decay", "value": f"demoted filler: {filler}"})
        log(f"Decay: removed stale filler \"{filler}\" (unused {DECAY_STALE_SESSIONS}+ sessions)", "info")
        demoted += 1

    # --- Vocabulary: demote stale terms ---
    vocab = prof.get("vocabulary", [])
    vocab_relevance = relevance.get("vocabulary", {})
    stale_vocab = []
    for term in vocab:
        last_relevant = vocab_relevance.get(term.lower(), 0)
        if last_relevant == 0:
            vocab_relevance[term.lower()] = session_n
            continue
        if session_n - last_relevant > DECAY_STALE_SESSIONS:
            stale_vocab.append(term)

    for term in stale_vocab:
        vocab.remove(term)
        _learn_event({"ts": now, "type": "decay", "value": f"demoted vocab: {term}"})
        log(f"Decay: removed stale vocab \"{term}\" (unused {DECAY_STALE_SESSIONS}+ sessions)", "info")
        demoted += 1

    if demoted or pruned:
        save_profile(prof)
        log(f"Decay sweep: {demoted} demoted, {pruned} pruned (session #{session_n})", "info")

    return demoted + pruned


# -- Trigger Word Detection ───────────────────────────────────────
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


DISFLUENCY_TYPES = {
    "block", "sound_rep", "word_rep", "prolongation", "interjection",
    "avoidance", "loop_compulsion",
}


def detect_triggers_llm(raw_text, output, prof):
    """LLM-assisted trigger word detection with disfluency type classification.
    Async, Layer 4 only. Returns dict: {word: disfluency_type}."""
    stats_inc("api_calls")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "The speaker stutters. Analyze this raw voice transcription and its "
                    "clean reconstruction. Identify TRIGGER WORDS — specific words the "
                    "speaker stuttered on — and classify the DISFLUENCY TYPE for each.\n\n"
                    "Disfluency types and detection patterns:\n"
                    "- sound_rep: Part-word/sound repetitions: 'Co-Co-Coca-Cola', 'buh-buh-blue'\n"
                    "- word_rep: Whole-word repetitions: 'I I I want', 'the the dog'\n"
                    "- prolongation: Elongated sounds: 'Sssssscience', 'Mmmmmom'\n"
                    "- block: Silent pause/fixation then a word bursts out (Whisper may hallucinate during the silence)\n"
                    "- interjection: Filler stacking used to delay a difficult word\n"
                    "- avoidance: Speaker uses a synonym or circumlocution to avoid a trigger word\n\n"
                    "Phonetic risk factors (words more likely to be triggers):\n"
                    "- Words starting with stop plosives: /p/, /b/, /t/, /d/, /k/, /g/\n"
                    "- Words starting with affricates: /tʃ/ (ch), /dʒ/ (j)\n"
                    "- First word of a sentence or clause boundary\n"
                    "- Consonant clusters at word onset (bl-, cr-, str-, etc.)\n\n"
                    "Return ONLY valid JSON:\n"
                    "{\"triggers\": [{\"word\": \"word1\", \"type\": \"block\"}, "
                    "{\"word\": \"word2\", \"type\": \"sound_rep\"}]}\n"
                    "If no stuttering detected, return {\"triggers\": []}\n"
                    "Be conservative — only include words with clear evidence of disfluency."
                )},
                {"role": "user", "content": f"Raw: {raw_text}\nClean: {output}"}
            ],
            max_tokens=200,
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        typed_triggers = {}
        for t in result.get("triggers", []):
            if isinstance(t, dict) and "word" in t:
                word = t["word"].lower()
                dtype = t.get("type", "unknown")
                if dtype not in DISFLUENCY_TYPES:
                    dtype = "unknown"
                typed_triggers[word] = dtype
            elif isinstance(t, str):
                # Backward compat: plain string without type
                typed_triggers[t.lower()] = "unknown"
        return typed_triggers
    except Exception as e:
        log(f"Trigger detect failed: {e}", "error")
        return {}


def add_trigger_words(new_triggers, prof):
    """Merge newly detected trigger words into profile.
    Accepts either a set of words or a dict of {word: disfluency_type}."""
    existing = {w.lower() for w in prof.get("trigger_words", [])}
    trigger_types = prof.get("trigger_types", {})
    added = []

    # Normalize input: set → dict with unknown type
    if isinstance(new_triggers, set):
        new_triggers = {w: "unknown" for w in new_triggers}

    for word, dtype in new_triggers.items():
        if word.lower() not in existing and len(word) > 1:
            prof.setdefault("trigger_words", []).append(word)
            existing.add(word.lower())
            # Per-language trigger bucket (#13)
            lang = detect_word_language(word)
            if lang in ("en", "ru"):
                by_lang = prof.setdefault("trigger_words_by_lang", {"en": [], "ru": []})
                by_lang.setdefault(lang, []).append(word)
            # Store disfluency type
            trigger_types[word.lower()] = dtype
            _learn_event({
                "ts": datetime.now().isoformat(),
                "type": "trigger",
                "value": word,
                "disfluency_type": dtype
            })
            log(f"Trigger detected: \"{word}\" ({dtype})", "info")
            added.append(word)
        elif word.lower() in existing and dtype != "unknown":
            # Update type for existing trigger if we now have a classification
            if trigger_types.get(word.lower()) in (None, "unknown"):
                trigger_types[word.lower()] = dtype

    prof["trigger_types"] = trigger_types
    if added:
        save_profile(prof)
        # Re-learn personalized onset weights with new trigger evidence
        learn_onset_weights(prof.get("trigger_words", []))
    elif trigger_types != prof.get("trigger_types"):
        save_profile(prof)  # save type updates even without new words
    return added


# -- Stutter Insights ─────────────────────────────────────────────
def _sample(items, limit=5):
    """Return up to `limit` items — most recent for lists, first keys for dicts."""
    if isinstance(items, dict):
        return list(items.keys())[:limit]
    if isinstance(items, list):
        return items[-limit:]
    return []

def build_stutter_insights(prof):
    """Deterministic Layer 4 insights from profile state. No API calls."""
    trigger_words = prof.get("trigger_words", [])
    filler_words = prof.get("filler_words", [])
    corrections = prof.get("corrections", {})
    session_count = db_session_count()

    insights = []

    # 1. Trigger cluster: 3+ trigger words accumulated
    if len(trigger_words) >= 3:
        tip = STUTTER_TIPS["trigger_cluster"]
        insights.append({
            "id": "trigger_cluster", "severity": "high",
            "title": tip["title"], "body": tip["body"], "source": tip["source"],
            "evidence": {"triggers": _sample(trigger_words, 5), "count": len(trigger_words)},
        })

    # 2. Heavy filler use: significantly more than the built-in baseline
    baseline = len(set(
        f.lower() for lang_fillers in KNOWN_FILLERS.values() for f in lang_fillers
    ) | {f.lower() for f in DEFAULT_PROFILE["filler_words"]})
    learned_fillers = max(0, len(filler_words) - baseline)
    if learned_fillers >= 5:
        tip = STUTTER_TIPS["high_filler_load"]
        insights.append({
            "id": "high_filler_load", "severity": "medium",
            "title": tip["title"], "body": tip["body"], "source": tip["source"],
            "evidence": {"total": len(filler_words), "learned": learned_fillers, "recent": _sample(filler_words, 6)},
        })

    # 3. Correction pattern: 5+ active corrections accumulated
    if len(corrections) >= 5:
        tip = STUTTER_TIPS["correction_pattern"]
        insights.append({
            "id": "correction_pattern", "severity": "medium",
            "title": tip["title"], "body": tip["body"], "source": tip["source"],
            "evidence": {"count": len(corrections), "sample": list(corrections.items())[:5]},
        })

    # 4. Dominant onset pattern: personalized phonetic fingerprint
    if _personal_dominant_onsets and len(trigger_words) >= 5:
        top = _personal_dominant_onsets[0]
        if top["pct"] >= 30:  # at least 30% concentration = real pattern
            tip = STUTTER_TIPS["dominant_onset_pattern"]
            onset_summary = ", ".join(
                f"/{d['onset']}/ ({d['pct']}%)" for d in _personal_dominant_onsets
            )
            insights.append({
                "id": "dominant_onset_pattern", "severity": "high",
                "title": tip["title"], "body": tip["body"], "source": tip["source"],
                "evidence": {
                    "dominant_onsets": onset_summary,
                    "total_triggers": len(trigger_words),
                    "top_onset": top["onset"],
                    "top_pct": top["pct"],
                    "example_words": [w for w in trigger_words
                                      if _extract_onset(w) == top["onset"]][:5],
                },
            })

    # 5. Fast growth: 3+ trigger detections in current engine run
    recent_triggers = sum(1 for e in _learn_events_snapshot() if e.get("type") == "trigger")
    if recent_triggers >= 3:
        tip = STUTTER_TIPS["fast_growth_triggers"]
        insights.append({
            "id": "fast_growth_triggers", "severity": "medium",
            "title": tip["title"], "body": tip["body"], "source": tip["source"],
            "evidence": {"recent_detections": recent_triggers},
        })

    # 6. Stable: no concerns, only if enough session data
    if not insights and session_count >= 10:
        tip = STUTTER_TIPS["stable_profile"]
        insights.append({
            "id": "stable_profile", "severity": "low",
            "title": tip["title"], "body": tip["body"], "source": tip["source"],
            "evidence": {"sessions": session_count, "triggers": len(trigger_words), "corrections": len(corrections)},
        })

    return insights[:MAX_INSIGHTS]


# -- DAF (Delayed Auditory Feedback) ──────────────────────────────
_daf_active = False
_daf_delay_ms = DAF_DEFAULT_DELAY_MS
_daf_stream = None
_daf_lock = threading.Lock()

def _daf_callback(indata, outdata, frames, time_info, status):
    """Stream mic → headphones with a ring-buffer delay."""
    buf = _daf_buf
    blen = len(buf)
    wp = _daf_wp[0]
    delay_samples = _daf_delay_samples[0]
    rp = (wp - delay_samples) % blen
    for i in range(frames):
        buf[wp % blen] = indata[i, 0]
        outdata[i, 0] = buf[rp % blen]
        wp += 1
        rp += 1
    _daf_wp[0] = wp % blen

def daf_start(delay_ms=None):
    global _daf_active, _daf_stream, _daf_buf, _daf_wp, _daf_delay_samples
    with _daf_lock:
        if _daf_active:
            return
        if delay_ms is not None:
            global _daf_delay_ms
            _daf_delay_ms = max(DAF_MIN_DELAY_MS, min(DAF_MAX_DELAY_MS, delay_ms))
        rate = NATIVE_RATE
        delay_samples = int(rate * _daf_delay_ms / 1000)
        buf_size = max(delay_samples * 4, rate)  # ring buffer
        _daf_buf = numpy.zeros(buf_size, dtype=numpy.float32)
        _daf_wp = [0]
        _daf_delay_samples = [delay_samples]
        _daf_stream = sd.Stream(
            samplerate=rate, channels=1, dtype='float32',
            device=(DEVICE, sd.default.device[1]),
            callback=_daf_callback, blocksize=256
        )
        _daf_stream.start()
        _daf_active = True
        log(f"DAF started ({_daf_delay_ms}ms delay)", "info")

def daf_stop():
    global _daf_active, _daf_stream
    with _daf_lock:
        if not _daf_active:
            return
        if _daf_stream:
            try:
                _daf_stream.stop()
                _daf_stream.close()
            except Exception:
                pass
            _daf_stream = None
            time.sleep(0.1)  # let Windows audio device fully release
        _daf_active = False
        log("DAF stopped", "info")

def daf_set_delay(delay_ms):
    global _daf_delay_ms
    delay_ms = max(DAF_MIN_DELAY_MS, min(DAF_MAX_DELAY_MS, delay_ms))
    _daf_delay_ms = delay_ms
    if _daf_active:
        rate = NATIVE_RATE
        _daf_delay_samples[0] = int(rate * delay_ms / 1000)
        log(f"DAF delay: {delay_ms}ms", "info")


# -- Audio ────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    chunk = indata.copy()
    # Always maintain rolling pre-roll buffer (last PREROLL_SEC of audio)
    with lock:
        _preroll_buffer.append(chunk)
        if _preroll_max_frames is not None:
            total = sum(len(c) for c in _preroll_buffer)
            while total > _preroll_max_frames and len(_preroll_buffer) > 1:
                total -= len(_preroll_buffer.pop(0))
        if is_recording:
            recording.append(chunk)

def _open_persistent_stream():
    """Open audio stream once and keep it running for the engine lifetime.
    This ensures the pre-roll buffer is always being fed, so F9 presses
    catch the user's first word instead of losing ~150-500ms to stream startup."""
    global stream, _preroll_max_frames
    _preroll_max_frames = int(NATIVE_RATE * PREROLL_SEC)
    stream = sd.InputStream(samplerate=NATIVE_RATE, channels=1,
                            device=DEVICE, callback=audio_callback)
    stream.start()

def start_recording():
    global is_recording, recording, target_hwnd, state
    with lock:
        if is_recording:
            return
        # Seed recording with pre-roll buffer so first word is captured
        recording = [c for c in _preroll_buffer]
        is_recording = True
        state = 'recording'
    target_hwnd = user32.GetForegroundWindow()

    # Brown Peak Risk: if Script Prep text is loaded, predict block difficulty
    # and warn the user to hold F9 longer on high-risk scripts
    if _last_prep_text and (time.time() - _last_prep_ts < _PREP_EXPIRY_SEC):
        peak = brown_peak_risk(_last_prep_text)
        if peak >= 0.7:
            log(f"Recording... ⚠ HIGH RISK ({peak:.0%}) — hold F9 through blocks", "rec")
        elif peak >= 0.5:
            log(f"Recording... moderate risk ({peak:.0%})", "rec")
        else:
            log("Recording...", "rec")
    else:
        log("Recording...", "rec")
    try:
        start_preview_stream()
    except Exception as e:
        log(f"Preview start failed: {e}", "error")
    # Stream is persistent (opened at startup) — just verify it's alive
    if stream is None or not stream.active:
        log("Stream not active -- reopening", "warn")
        try:
            _open_persistent_stream()
        except Exception as e:
            log(f"Stream error: {e}", "error")
            with lock:
                is_recording = False
                state = 'error'
            threading.Timer(3, lambda: set_state('idle')).start()

def stop_recording():
    global is_recording, state, last_stop_time
    now = time.time()
    if now - last_stop_time < 1.0:
        return
    last_stop_time = now
    with lock:
        if not is_recording:
            return
        is_recording = False
        state = 'processing'
    # Stream stays open (persistent for pre-roll buffer) — do NOT close it
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


def compute_wer(reference, hypothesis):
    """Word Error Rate between reference (intended) and hypothesis (ASR output).
    Returns (wer_float, substitutions, deletions, insertions)."""
    ref = reference.lower().split()
    hyp = hypothesis.lower().split()
    r, h = len(ref), len(hyp)
    # Dynamic programming edit distance
    d = [[0] * (h + 1) for _ in range(r + 1)]
    for i in range(r + 1):
        d[i][0] = i
    for j in range(h + 1):
        d[0][j] = j
    for i in range(1, r + 1):
        for j in range(1, h + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    # Backtrace for S/D/I counts
    i, j = r, h
    s_count = d_count = i_count = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]:
            i -= 1; j -= 1
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            s_count += 1; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            d_count += 1; i -= 1
        else:
            i_count += 1; j -= 1
    wer = d[r][h] / max(r, 1)
    return (wer, s_count, d_count, i_count)



def _text_nearly_identical(raw, clean, threshold=0.85):
    """Check if raw and clean text are nearly identical.
    Uses both length ratio AND word overlap — both must exceed threshold.
    Stuttered speech has high word overlap after disfluency removal but LOW
    length ratio (stuttered text is inflated by repetitions). This ensures
    Falcon still validates real reconstructions while skipping no-ops.
    Zero API cost."""
    if not raw or not clean:
        return False
    raw_words = raw.split()
    clean_words = clean.split()
    if not raw_words or not clean_words:
        return False
    # Length ratio: stuttered text is always longer than clean
    length_ratio = min(len(raw_words), len(clean_words)) / max(len(raw_words), len(clean_words))
    if length_ratio < threshold:
        return False
    # Word overlap: shared vocabulary
    raw_set = set(w.lower().strip(".,!?;:'\"") for w in raw_words)
    clean_set = set(w.lower().strip(".,!?;:'\"") for w in clean_words)
    total = max(len(raw_set), len(clean_set))
    overlap = len(raw_set & clean_set) / total if total > 0 else 0
    return overlap >= threshold


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

_CRITICAL_TOKEN_RE = re.compile(
    r'\b(?:\d+(?:[.,]\d+)?%?|\$?\d+(?:,\d{3})*(?:\.\d+)?)\b'  # numbers, percentages, dollar amounts
)

def _check_critical_retention(raw_text, clean_text):
    """Check if numbers and dollar amounts from raw text survived reconstruction.

    Returns list of lost tokens, or empty list if all preserved.
    Zero cost — regex only, no API calls.
    """
    critical = _CRITICAL_TOKEN_RE.findall(raw_text)
    if not critical:
        return []
    clean_lower = clean_text.lower()
    lost = [t for t in critical if t.lower() not in clean_lower]
    return lost


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

# -- Whisper API (enhanced) ────────────────────────────────────────
def _build_whisper_prompt():
    """Build Whisper decoder prompt: Script Prep > Clipboard Bias > generic fluency.

    Priority order:
    1. Script Prep (explicit user-provided text — highest accuracy)
    2. Clipboard Predictor bias (background-computed synonyms for high-risk words)
    3. Generic fluency-biasing prompt (fallback)

    Script Prep as initial_prompt is the key insight: Whisper's autoregressive
    decoder treats the prompt as "previously transcribed text." When we seed it
    with the intended speech (from Script Prep), the decoder's beam search has
    the answer key before it transcribes. This dramatically reduces hallucination
    on blocked or disfluent segments.
    """
    # Priority 1: explicit Script Prep text (don't consume — covert detection needs it too)
    if _last_prep_text and (time.time() - _last_prep_ts < _PREP_EXPIRY_SEC):
        prep = _last_prep_text[:500]
        log(f"Whisper seeded with Script Prep ({len(prep)} chars)", "info")
        return prep
    # Priority 2: clipboard predictor bias (pre-computed, never blocks)
    if _clipboard_predictor:
        clip_bias = _clipboard_predictor.get_prompt_bias()
        if clip_bias:
            log(f"Whisper seeded with Clipboard Predictor ({len(clip_bias)} chars)", "info")
            return clip_bias
    # Priority 3: layer-aware fallback
    if current_layer == 1:
        # L1 = verbatim transcription. Do NOT bias Whisper toward fluency —
        # that causes it to silently drop fillers and repetitions.
        return "Transcribe exactly what the speaker says, including all words, repetitions, and filler sounds."
    # L2+: bias toward clean output since reconstruction handles the rest
    return "Clear, fluent speech. Transcribe intended words only, not repetitions or filler sounds."


def _whisper_single_call(filepath, temperature, prompt_text, max_retries=3):
    """Single ASR call returning verbose JSON with segment data.

    Layer-conditional dispatch:
      - L4 (clinical): cloud whisper-1 with verbose_json — gives the full
        per-segment metadata (avg_logprob, no_speech_prob, timestamps) that the
        Sonnet-4.6-extended-thinking reconstructor needs to reason about block
        suspects, multi-temp disagreements, prosodic stress windows, etc.
        Moonshine's flat output is useless for this — verified empirically
        that gpt-4o-transcribe also doesn't return verbose_json (HTTP 400).
      - L1/L2/L3: local ASR (Moonshine -> Vosk via asr_local). Fast paste path.

    Returns dict with: text, segments, engine.
    Retries up to max_retries on transient errors.
    """
    # L4 → cloud whisper-1 for rich segment metadata
    if current_layer >= 4 and client is not None:
        last_err = None
        for attempt in range(max_retries):
            try:
                with open(filepath, "rb") as f:
                    resp = client.audio.transcriptions.create(
                        file=f,
                        model="whisper-1",
                        response_format="verbose_json",
                        temperature=float(temperature) if temperature is not None else 0.0,
                        prompt=prompt_text or "",
                    )
                d = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
                stats_inc("api_calls")
                stats_inc("cloud_transcriptions")
                return {
                    "text": (d.get("text") or "").strip(),
                    "segments": d.get("segments", []) or [],
                    "engine": "whisper-1",
                }
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    log(f"Cloud whisper-1 error ({str(e)[:80]}), retry {attempt+1}/{max_retries} in {wait}s", "warn")
                    time.sleep(wait)
                    continue
                log(f"Cloud whisper-1 exhausted retries: {str(e)[:120]} — falling back to local", "warn")
                break  # fall through to local path below
        # If we got here after exhausting cloud retries, drop into local fallback.

    # L1/L2/L3 (and L4 fallback): local ASR chain (Moonshine -> Vosk)
    if _local_transcribe_fn is None:
        raise RuntimeError(
            "Local ASR not available. Install Moonshine and/or Vosk: "
            "see local/whisper_local.py + local/vosk_local.py for setup."
        )

    last_err = None
    for attempt in range(max_retries):
        try:
            result = _local_transcribe_fn(filepath, temperature, prompt_text, LANGUAGE, LOCAL_WHISPER_MODEL_SIZE)
            stats_inc("local_transcriptions")
            return result
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                log(f"Local ASR error ({str(e)[:80]}), retry {attempt+1}/{max_retries} in {wait}s", "warn")
                time.sleep(wait)
                continue
            log(f"Local ASR exhausted retries: {str(e)[:120]}", "error")
            raise last_err


def get_patience_timeout() -> float:
    """Return silence timeout based on current layer and situation.

    In patience mode (Layer 4 or High Stress), the engine tolerates longer
    silences before considering speech complete — critical for PWS whose blocks
    look like silence to both human listeners and ASR systems.
    (Apple ML Research 2023: default endpointer cuts off PWS 23.8% of the time;
    extending to 4.5s reduces false cutoffs to <3%.)
    """
    if current_layer >= 4 or current_situation == "high_stress":
        return PATIENCE_STUTTER
    return PATIENCE_DEFAULT


def _extract_low_confidence_segments(verbose_result, risk_threshold=-0.7):
    """Extract segments where Whisper is uncertain (low avg_logprob).

    avg_logprob closer to 0 = confident. Below threshold = uncertain.
    Segments near Brown high-risk positions (early sentence, consonant-initial
    content words) are flagged for targeted L4 reconstruction.

    Also detects potential blocks: segments with high no_speech_prob that Whisper
    nearly classified as silence. The API drops these internally at its own
    threshold (~0.6), but segments that survive with no_speech_prob > our
    WHISPER_NO_SPEECH_THRESHOLD are flagged as possible block artifacts —
    Whisper hallucinated filler into what was really strained silence.

    Returns list of {text, avg_logprob, no_speech_prob, position, brown_risk, block_suspect}
    """
    segments = verbose_result.get("segments", [])
    if not segments:
        return []

    flagged = []
    full_text = verbose_result.get("text", "")
    words_so_far = 0

    for seg in segments:
        # Cloud Whisper emits floats for these; local Moonshine emits None because
        # the ONNX decoder doesn't surface per-segment confidence. Coerce None →
        # safe defaults so downstream comparisons don't crash:
        #   avg_logprob=0.0 → max confidence (won't flag as low-conf)
        #   no_speech_prob=0.0 → definitely speech (won't flag as block suspect)
        #   compression_ratio=1.0 → normal entropy (won't flag as repetition loop)
        avg_lp = seg.get("avg_logprob") or 0.0
        no_speech = seg.get("no_speech_prob") or 0.0
        compression_ratio = seg.get("compression_ratio") or 1.0
        seg_text = seg.get("text", "").strip()

        if not seg_text:
            continue

        seg_words = re.findall(r'\b\w+\b', seg_text)
        n_total = len(re.findall(r'\b\w+\b', full_text)) if full_text else 1

        # Check if this segment has Brown risk factors
        brown_risk = 0.0
        for i, w in enumerate(seg_words):
            brown_risk = max(brown_risk, predict_phonetic_risk(
                w, sentence_position=words_so_far + i, sentence_length=n_total
            ))

        words_so_far += len(seg_words)

        # Block suspect: high no_speech_prob means Whisper nearly classified this as
        # silence. For stutterers, that "silence" is a block — strained, effortful,
        # with possible laryngeal tension. Whisper hallucinated text into the gap.
        # Patience mode (L4/high_stress) raises threshold to 0.6 — more tolerant
        # of silence in audio, fewer false block detections.
        _nst = 0.6 if get_patience_timeout() > PATIENCE_DEFAULT else WHISPER_NO_SPEECH_THRESHOLD
        block_suspect = no_speech > _nst
        # Compression ratio > 2.4 = Whisper stuck in repetition loop (OpenAI's own threshold).
        # The decoder output this segment with abnormally low entropy, meaning it's
        # likely "bad bad bad..." or "Thank you Thank you..." hallucination garbage.
        repetition_loop = compression_ratio > 2.4

        # Flag if: low confidence AND near high-risk position, OR block suspect, OR repetition loop
        if avg_lp < risk_threshold or (avg_lp < -0.4 and brown_risk >= 0.5) or block_suspect or repetition_loop:
            flagged.append({
                "text": seg_text,
                "avg_logprob": round(avg_lp, 3),
                "no_speech_prob": round(no_speech, 3),
                "compression_ratio": round(compression_ratio, 2),
                "position": words_so_far,
                "brown_risk": round(brown_risk, 2),
                "block_suspect": block_suspect,
                "repetition_loop": repetition_loop,
            })
            if block_suspect:
                log(f"Block suspect: \"{seg_text}\" (no_speech_prob={no_speech:.2f}) — likely hallucinated over a block", "info")
            if repetition_loop:
                log(f"Repetition loop: \"{seg_text}\" (compression_ratio={compression_ratio:.2f}) — Whisper hallucination", "warn")
                stats_inc("repetition_loops")

    return flagged


def _multi_temperature_vote(filepath, prompt_text):
    """Call Whisper at multiple temperatures, flag disagreements.

    Three decoding passes on the same audio. Where they agree = confident.
    Where they disagree = almost certainly a disfluency artifact.

    Returns:
      text: best transcription (temperature=0 unless outvoted)
      segments: verbose segments from primary call
      disagreements: list of {position, variants: [str, str, str]}
      all_texts: list of all transcriptions
    """
    # Fire all 3 temperatures in PARALLEL — total time = max(call1, call2, call3)
    # instead of sum(call1, call2, call3). Cuts 4-6 sec overhead to ~0-1 sec.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = [None] * len(WHISPER_MULTI_TEMPS)
    with ThreadPoolExecutor(max_workers=len(WHISPER_MULTI_TEMPS)) as pool:
        futures = {
            pool.submit(_whisper_single_call, filepath, temp, prompt_text): i
            for i, temp in enumerate(WHISPER_MULTI_TEMPS)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            stats_inc("multi_temp_votes")

    primary = results[0]  # temp=0 is authoritative by default
    all_texts = [r.get("text", "").strip() for r in results]

    # Quick check: if all three agree, no need for analysis
    if len(set(all_texts)) == 1:
        return {
            "text": all_texts[0],
            "segments": primary.get("segments", []),
            "disagreements": [],
            "all_texts": all_texts,
        }

    # Find disagreements at word level
    word_lists = [re.findall(r'\b\w+\b', t.lower()) for t in all_texts]
    max_len = max(len(wl) for wl in word_lists)
    disagreements = []

    for i in range(max_len):
        words_at_pos = []
        for wl in word_lists:
            words_at_pos.append(wl[i] if i < len(wl) else "<END>")
        if len(set(words_at_pos)) > 1:
            disagreements.append({
                "position": i,
                "variants": words_at_pos,
            })

    if disagreements:
        stats_inc("multi_temp_disagreements")
        log(f"Multi-temp voting: {len(disagreements)} disagreements across {len(all_texts[0].split())} words", "info")

    return {
        "text": all_texts[0],  # temp=0 primary
        "segments": primary.get("segments", []),
        "disagreements": disagreements,
        "all_texts": all_texts,
    }


def whisper_transcribe(filepath):
    """Primary ASR: OpenAI Whisper API (cloud). Local Moonshine kicks in as fallback
    when the API path fails (no key, network down, etc.) — see `local/whisper_local.py`.

    Returns dict with:
      text: final transcription
      segments: verbose per-segment data (cloud path only; local fallback emits
                a single synthetic segment)
      low_confidence: flagged uncertain segments (cloud path only)
      disagreements: multi-temp voting disagreements (cloud path only)
      whisper_meta: {prompt_source, prompt_length, temperatures, n_api_calls, engine}
    """
    prompt_text = _build_whisper_prompt()
    with _stats_lock:
        n_calls_before = stats["api_calls"]

    # Multi-temp voting fires when:
    # 1) Paralinguistic + transcribe both ON (needs disagreement data for event detection)
    # 2) Layer 4 (stutter) — disagreements help target disfluency artifacts in reconstruction
    # Otherwise single call = 1/3 the cost.
    _use_multi = WHISPER_MULTI_TEMP and (
        (paralinguistic_enabled and paralinguistic_transcribe)
        or current_layer >= 4
    )
    if _use_multi:
        vote = _multi_temperature_vote(filepath, prompt_text)
        text = vote["text"]
        segments = vote["segments"]
        disagreements = vote["disagreements"]
        all_texts = vote["all_texts"]
    else:
        result = _whisper_single_call(filepath, WHISPER_TEMP, prompt_text)
        text = result.get("text", "").strip()
        segments = result.get("segments", [])
        disagreements = []
        all_texts = [text]

    # Extract low-confidence segments for targeted reconstruction
    low_confidence = _extract_low_confidence_segments(
        {"text": text, "segments": segments}
    )

    if low_confidence:
        log(f"Whisper low-confidence segments: {len(low_confidence)} flagged", "info")

    global _block_count
    _block_count = sum(1 for s in low_confidence if s.get("block_suspect"))

    with _stats_lock:
        n_calls_delta = stats["api_calls"] - n_calls_before

    return {
        "text": text,
        "segments": segments,
        "low_confidence": low_confidence,
        "disagreements": disagreements,
        "all_texts": all_texts,
        "whisper_meta": {
            "prompt_source": "script_prep" if (_last_prep_text and time.time() - _last_prep_ts < _PREP_EXPIRY_SEC) else ("clipboard" if (_clipboard_predictor and _clipboard_predictor.get_prompt_bias()) else "default"),
            "prompt_length": len(prompt_text),
            "temperatures": WHISPER_MULTI_TEMPS if WHISPER_MULTI_TEMP else [WHISPER_TEMP],
            "n_api_calls": n_calls_delta,
        }
    }


# -- Shadow Utterance (#12) ────────────────────────────────────
# "What you probably meant to say" — ground truth for avoidance measurement.
# For prepped text: Script Prep IS the shadow (zero cost).
# For unprepped text: one LLM call to infer intended speech from partial context.
# The diff between shadow and actual transcript = avoidance drift score.
# L4 only (extra API cost).

_shadow_history = []  # list of {ts, shadow, actual, drift_score, source}
_shadow_lock = threading.Lock()
_MAX_SHADOW_HISTORY = 50


def generate_shadow_utterance(raw_text, prof):
    """Generate the 'shadow utterance' — what the speaker probably intended to say.

    If Script Prep text is available, use it directly (the user already told us
    what they planned to say). Otherwise, infer from context + trigger history.

    Returns: {shadow: str, source: 'prep'|'inferred', drift_score: float}
    """
    # Check if Script Prep text is available (hasn't been consumed yet by covert detection)
    if _last_prep_text and (time.time() - _last_prep_ts < _PREP_EXPIRY_SEC):
        shadow = _last_prep_text
        source = "prep"
    else:
        # Infer shadow utterance via LLM (one extra call, L4 cost)
        triggers = prof.get("trigger_words", [])[:15]
        covert = prof.get("covert_profile", {}).get("avoidance_pairs", {})
        # Collect known avoidance substitutions
        known_swaps = {}
        for sit_data in covert.values():
            for word, data in sit_data.items():
                for sub in data.get("common_substitutes", []):
                    known_swaps[sub] = word  # substitute → original intended

        stats_inc("api_calls")
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": (
                        "You are analyzing speech from a person who stutters. "
                        "They may have substituted words to avoid ones they find difficult to say. "
                        "Given their raw speech, reconstruct what they ORIGINALLY INTENDED to say "
                        "before avoidance kicked in.\n\n"
                        "Known trigger words (words they struggle with): " +
                        ", ".join(triggers[:10]) + "\n"
                        "Known substitution patterns: " +
                        "; ".join(f'"{sub}" was used instead of "{orig}"'
                                 for sub, orig in list(known_swaps.items())[:8]) +
                        "\n\nReturn ONLY the intended utterance. No explanation."
                    )},
                    {"role": "user", "content": raw_text}
                ],
                max_tokens=200,
                temperature=0
            )
            shadow = resp.choices[0].message.content.strip()
            source = "inferred"
        except Exception as e:
            log(f"Shadow utterance failed: {e}", "error")
            return {"shadow": raw_text, "source": "fallback", "drift_score": 0.0}

    # Compute avoidance drift: word-level diff between shadow and actual
    shadow_words = set(re.findall(r'\b\w+\b', shadow.lower()))
    actual_words = set(re.findall(r'\b\w+\b', raw_text.lower()))
    # Words in shadow but not in actual = probably avoided
    avoided = shadow_words - actual_words - FUNCTION_WORDS
    # Words in actual but not in shadow = substitutes used
    substituted = actual_words - shadow_words - FUNCTION_WORDS
    # Drift = fraction of content words that changed
    content_total = len(shadow_words - FUNCTION_WORDS)
    drift_score = len(avoided) / max(content_total, 1)

    entry = {
        "ts": datetime.now().isoformat(),
        "shadow": shadow,
        "actual": raw_text,
        "drift_score": round(drift_score, 3),
        "avoided_words": list(avoided)[:10],
        "substitute_words": list(substituted)[:10],
        "source": source,
    }
    with _shadow_lock:
        _shadow_history.append(entry)
        if len(_shadow_history) > _MAX_SHADOW_HISTORY:
            _shadow_history.pop(0)

    if drift_score > 0.15:
        log(f"Shadow drift: {drift_score:.0%} — {len(avoided)} words avoided [{source}]", "info")

    return entry


def compute_avoidance_trend():
    """Compute rolling avoidance drift trend from shadow history.
    Returns: avg drift over last 10 recordings, trend direction."""
    with _shadow_lock:
        history_snapshot = list(_shadow_history)
    if not history_snapshot:
        return {"avg_drift": 0.0, "trend": "stable", "n": 0}
    recent = history_snapshot[-10:]
    drifts = [e["drift_score"] for e in recent]
    avg = sum(drifts) / len(drifts)
    # Trend: compare first half vs second half
    if len(drifts) >= 4:
        first_half = sum(drifts[:len(drifts)//2]) / (len(drifts)//2)
        second_half = sum(drifts[len(drifts)//2:]) / (len(drifts) - len(drifts)//2)
        if second_half > first_half + 0.05:
            trend = "increasing"
        elif second_half < first_half - 0.05:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"
    return {"avg_drift": round(avg, 3), "trend": trend, "n": len(drifts)}


# -- Speech Rate & Pause Analysis (#11) ────────────────────────
# Pure numpy signal processing: RMS energy thresholding for speech/silence
# segmentation. No ML, no API calls. ~20 lines of signal processing.
# Outputs: pause_ratio, speaking_rate_sps (syllables/sec), dynamic severity modifier

_SPEECH_RMS_THRESHOLD = 0.015     # RMS below this = silence (tuned for 16kHz whisper-quality audio)
_FRAME_SIZE_SAMPLES = 320         # 20ms frames at 16kHz (standard VAD frame size)
_MIN_PAUSE_FRAMES = 5             # 100ms minimum silence to count as a "pause" (not just consonant gap)
_last_speech_metrics = {}         # cached for dashboard
_last_low_conf_segments = []     # cached low confidence Whisper segments for dashboard
_last_avg_logprob = 0.0          # cached avg_logprob from last session


def analyze_speech_rate(audio_data, sample_rate=16000):
    """Compute speech rate and pause ratio from raw audio.

    Uses RMS energy thresholding to segment speech vs silence.
    Syllable estimate = voiced segment transitions (onset counting).
    Pause = consecutive silent frames >= _MIN_PAUSE_FRAMES (100ms).

    Returns dict:
      pause_ratio: float (0.0 = no pauses, 1.0 = all silence)
      speaking_rate_sps: float (syllables per second of speech)
      n_pauses: int (count of distinct pauses)
      total_duration_s: float
      speech_duration_s: float
      severity_modifier: float (0.0-0.6 additive boost for reconstruction)
    """
    global _last_speech_metrics
    total_samples = len(audio_data)
    if total_samples < _FRAME_SIZE_SAMPLES * 3:
        return {"pause_ratio": 0.0, "speaking_rate_sps": 0.0, "n_pauses": 0,
                "total_duration_s": total_samples / sample_rate,
                "speech_duration_s": 0.0, "severity_modifier": 0.0}

    # Frame-level RMS energy
    n_frames = total_samples // _FRAME_SIZE_SAMPLES
    frames = audio_data[:n_frames * _FRAME_SIZE_SAMPLES].reshape(n_frames, _FRAME_SIZE_SAMPLES)
    rms = numpy.sqrt(numpy.mean(frames ** 2, axis=1))

    # Classify frames: speech (1) or silence (0)
    is_speech = (rms >= _SPEECH_RMS_THRESHOLD).astype(int)

    speech_frames = int(numpy.sum(is_speech))
    silence_frames = n_frames - speech_frames
    frame_duration = _FRAME_SIZE_SAMPLES / sample_rate

    # Count distinct pauses (consecutive silent frames >= threshold)
    n_pauses = 0
    silent_run = 0
    for val in is_speech:
        if val == 0:
            silent_run += 1
        else:
            if silent_run >= _MIN_PAUSE_FRAMES:
                n_pauses += 1
            silent_run = 0
    if silent_run >= _MIN_PAUSE_FRAMES:
        n_pauses += 1

    # Count syllable-like onsets (silence→speech transitions)
    # Each onset ≈ one syllable nucleus (vowel onset)
    transitions = numpy.diff(is_speech)
    syllable_onsets = int(numpy.sum(transitions == 1))  # 0→1 transitions
    syllable_onsets = max(syllable_onsets, 1)  # at least one syllable if we have speech

    total_duration = total_samples / sample_rate
    speech_duration = speech_frames * frame_duration
    pause_duration = silence_frames * frame_duration

    pause_ratio = pause_duration / total_duration if total_duration > 0 else 0.0
    speaking_rate = syllable_onsets / speech_duration if speech_duration > 0.1 else 0.0

    # Dynamic severity modifier:
    # High pause ratio = speaker is blocking → bump reconstruction aggressiveness
    # Normal conversational pause_ratio ≈ 0.25-0.35
    # Stuttered speech pause_ratio ≈ 0.40-0.70
    # Severe blocking pause_ratio > 0.70
    if pause_ratio > 0.60:
        severity_mod = 0.6    # heavy blocking — max boost
    elif pause_ratio > 0.45:
        severity_mod = 0.4    # significant pausing
    elif pause_ratio > 0.35:
        severity_mod = 0.2    # mild pausing above normal
    else:
        severity_mod = 0.0    # normal range

    # Also: abnormally slow speaking rate (< 2 syl/sec vs normal ~4-5)
    if speaking_rate > 0 and speaking_rate < 2.0:
        severity_mod = max(severity_mod, 0.3)

    metrics = {
        "pause_ratio": round(pause_ratio, 3),
        "speaking_rate_sps": round(speaking_rate, 2),
        "n_pauses": n_pauses,
        "total_duration_s": round(total_duration, 2),
        "speech_duration_s": round(speech_duration, 2),
        "severity_modifier": round(severity_mod, 2),
    }
    _last_speech_metrics = metrics
    return metrics


# -- Layer 5: Paralinguistic Event Detection ─────────────────────
# Detects non-verbal events (laughter, cough, sigh, breathing, throat-clearing,
# pauses) using audio analysis + Whisper's own errors as detection signals.
# Key insight (Zhang): 96.1% of ASR errors cluster within ±1s of a paralinguistic
# event. Uses existing multi-temp disagreements and low-confidence segments to find
# candidate windows, then classifies via HNR + error-type signatures.
# No new dependencies beyond numpy/scipy.

# Phase 1 tags — covers all detectable paralinguistic events
# NVS-38K taxonomy + Trouvain's conversational NVVs
PARALINGUISTIC_TAGS = [
    "Laughter", "Cough", "Sigh", "Pause", "Throat-clearing", "Breathing",
    "Sneezing", "Yawning", "Crying", "Sniff", "Gasp"
]

# Detection thresholds (derived from Gupta et al. + Zhang + NVS-38K)
_HNR_SPEECH_THRESHOLD = 4.0       # dB — below this = paralinguistic, not speech
_HNR_CERTAIN_THRESHOLD = 2.0      # dB — below this = high-confidence paralinguistic event
_MIN_EVENT_DURATION_S = 0.3       # NVS-38K: discard events shorter than 300ms
_MIN_LAUGHTER_DURATION_S = 1.0    # Laughter requires 1000ms sustained evidence
_MIN_YAWNING_DURATION_S = 1.5    # Yawning is long and breathy (1.5s+)
_MIN_CRYING_DURATION_S = 1.0     # Crying needs sustained irregular pattern
_MIN_SNIFF_DURATION_S = 0.3      # Sniff is very short nasal burst
_MIN_GASP_DURATION_S = 0.3       # Gasp is sudden, short intake
_CONFIDENCE_FLOOR = 0.15          # Discard candidates below this combined score
_EVENT_WINDOW_S = 1.0             # +-1s around error clusters (Zhang's temporal error zone)
_ENERGY_FLOOR_DB = -35.0          # NVS-38K: discard events below -35 dB

# Gupta probability masking thresholds (Interspeech 2013)
# T0: aggressive suppression — if event prob drops below this, zero it out
# T1: confirmation threshold — only commit event if prob exceeds this
_GUPTA_T0 = 0.02
_GUPTA_T1 = 0.98

# ZCR thresholds (Zhang: insertion-prone events have low ZCR)
_ZCR_LOW_THRESHOLD = 1500.0      # Below this = aperiodic noise (sigh, throat-clear)
_ZCR_NASAL_THRESHOLD = 1000.0    # Very low ZCR + short = nasal event (sniff)

# Error-type-to-event mapping (Zhang: "Composition of error types by event type")
# Laughter: 48.9% substitutions, 39.1% deletions -> S+D dominant
# Sigh: 50% before-event errors, insertions 10.57x more likely than laughter
# Throat-clearing: 46.7% during-event errors, 40% insertions, 5.86x more likely
_LAUGHTER_SD_RATIO = 0.6    # S+D must be >=60% of errors in window for laughter
_INSERTION_RATIO = 0.35      # Insertions >=35% of errors -> sigh or throat-clearing

# Cached paralinguistic events from last pipeline run (for dashboard)
_last_paralinguistic_events = []


# ── SileroVAD pre-filter ──────────────────────────────────────────
# Whisper hallucinates 40.3% of the time on non-speech audio (Barański et al., 2025).
# Stutterers produce blocks (silence) that Whisper fills with fabricated text.
# Solution: run VAD BEFORE Whisper, cross-reference after. Whisper output that
# maps to a non-speech VAD segment is flagged as hallucination.
# SileroVAD runs via ONNX (~300KB model, ~5ms per second of audio on CPU).
# Research: combined VAD + pattern filter drops WER from 104.8% to 6.5%.

_vad_model = None
_vad_model_path = Path(__file__).parent / "silero_vad.onnx"

def _load_vad_model():
    """Lazy-load SileroVAD ONNX model."""
    global _vad_model
    if _vad_model is not None:
        return _vad_model
    if not _vad_model_path.exists():
        return None
    try:
        import onnxruntime as ort
        _vad_model = ort.InferenceSession(
            str(_vad_model_path),
            providers=["CPUExecutionProvider"]
        )
        return _vad_model
    except Exception as e:
        log(f"SileroVAD load failed: {e}", "warn")
        return None


def detect_speech_segments(audio_data, sample_rate=16000, threshold=0.35,
                           min_speech_ms=250, min_silence_ms=300):
    """Run SileroVAD on audio, return list of speech/silence segments.

    Returns list of dicts:
      [{"start_s": 0.0, "end_s": 1.2, "is_speech": True},
       {"start_s": 1.2, "end_s": 2.8, "is_speech": False},  # block candidate
       {"start_s": 2.8, "end_s": 4.1, "is_speech": True}, ...]

    threshold: VAD speech probability threshold (lower = more permissive,
               set conservatively for stutterers — better to send a strained
               sound to Whisper than to miss real speech)
    min_speech_ms: minimum speech segment duration to keep
    min_silence_ms: minimum silence duration to mark as block candidate
    """
    model = _load_vad_model()
    if model is None:
        return []  # no VAD model → skip, pipeline continues normally

    try:
        # SileroVAD expects 16kHz mono float32, processes in 512-sample chunks (32ms)
        if sample_rate != 16000:
            from scipy.signal import resample
            audio_data = resample(audio_data, int(len(audio_data) * 16000 / sample_rate))
            sample_rate = 16000

        window_size = 512  # 32ms at 16kHz — SileroVAD's native chunk size
        audio = audio_data.astype(numpy.float32)

        # SileroVAD v5+ ONNX inputs: input(float[1, chunk]), state(float[2,1,128]), sr(int64 scalar)
        state = numpy.zeros((2, 1, 128), dtype=numpy.float32)
        sr = numpy.array(sample_rate, dtype=numpy.int64)

        # Process chunks, collect per-chunk speech probability
        probs = []
        for i in range(0, len(audio) - window_size + 1, window_size):
            chunk = audio[i:i + window_size].reshape(1, -1)
            ort_inputs = {"input": chunk, "state": state, "sr": sr}
            out = model.run(None, ort_inputs)
            prob = float(out[0][0][0])
            state = out[1]
            probs.append(prob)

        if not probs:
            return []

        # Convert chunk probabilities to segments
        chunk_duration = window_size / sample_rate
        segments = []
        current_is_speech = probs[0] >= threshold
        current_start = 0.0

        for i, prob in enumerate(probs):
            is_speech = prob >= threshold
            if is_speech != current_is_speech:
                end_s = i * chunk_duration
                segments.append({
                    "start_s": round(current_start, 3),
                    "end_s": round(end_s, 3),
                    "is_speech": current_is_speech,
                })
                current_start = end_s
                current_is_speech = is_speech

        # Close final segment
        total_s = len(audio) / sample_rate
        segments.append({
            "start_s": round(current_start, 3),
            "end_s": round(total_s, 3),
            "is_speech": current_is_speech,
        })

        # Merge short segments (avoid fragmenting speech/silence)
        merged = []
        for seg in segments:
            duration_ms = (seg["end_s"] - seg["start_s"]) * 1000
            if seg["is_speech"] and duration_ms < min_speech_ms and merged:
                # Too short to be real speech — merge with previous
                merged[-1]["end_s"] = seg["end_s"]
            elif not seg["is_speech"] and duration_ms < min_silence_ms and merged:
                # Too short to be a real block — merge with previous
                merged[-1]["end_s"] = seg["end_s"]
            else:
                merged.append(dict(seg))

        return merged

    except Exception as e:
        log(f"VAD error: {e}", "warn")
        return []  # fail open — pipeline continues without VAD


def vad_filter_whisper_segments(whisper_segments, vad_segments):
    """Cross-reference Whisper output segments with VAD segments.

    For each Whisper segment that falls predominantly within a non-speech VAD
    window, flag it as a hallucination candidate. This catches text that Whisper
    fabricated during silence/blocks — the 40.3% hallucination rate on non-speech.

    Returns (cleaned_segments, block_markers):
      cleaned_segments: Whisper segments with hallucinated ones removed
      block_markers: list of {"start_s", "end_s"} for detected blocks
    """
    if not vad_segments or not whisper_segments:
        return whisper_segments, []

    cleaned = []
    block_markers = []

    for wseg in whisper_segments:
        w_start = wseg.get("start", 0)
        w_end = wseg.get("end", 0)
        w_mid = (w_start + w_end) / 2

        # Find which VAD segment this Whisper segment's midpoint falls in
        in_speech = True  # default: trust Whisper if VAD can't decide
        for vseg in vad_segments:
            if vseg["start_s"] <= w_mid <= vseg["end_s"]:
                in_speech = vseg["is_speech"]
                break

        if in_speech:
            cleaned.append(wseg)
        else:
            # Whisper produced text during a non-speech window → hallucination
            block_markers.append({
                "start_s": round(w_start, 2),
                "end_s": round(w_end, 2),
                "whisper_text": wseg.get("text", "").strip(),
            })

    return cleaned, block_markers


def compute_hnr(audio_segment, sample_rate=16000):
    """Compute Harmonics-to-Noise Ratio via autocorrelation.

    HNR measures how much of the signal is periodic (harmonic/voiced) vs
    aperiodic (noise). Speech has high HNR (>4 dB). Coughs, sighs, breathing
    have low HNR (<4 dB). This is the core acoustic discriminator for
    paralinguistic event detection.

    Method: normalized autocorrelation, find peak in pitch range (80-500 Hz),
    HNR = 10 * log10(r_peak / (1 - r_peak)) where r_peak is the normalized
    autocorrelation at the pitch lag.

    Returns HNR in dB. Higher = more harmonic. Returns 20.0 (safe default
    = "assume speech") for degenerate inputs (too short, silence, etc).
    """
    import numpy as np

    min_samples = int(sample_rate / 80) * 2  # Need ≥2 pitch periods at lowest pitch
    if len(audio_segment) < min_samples:
        return 20.0  # Too short to analyze → assume speech (safe default)

    # Remove DC offset
    segment = audio_segment - np.mean(audio_segment)

    # Check for silence (all zeros or near-zero energy)
    rms = np.sqrt(np.mean(segment ** 2))
    if rms < 1e-6:
        return 20.0  # Silence → not a paralinguistic event, assume speech

    # Normalized autocorrelation via numpy
    n = len(segment)
    # Use scipy.signal.fftconvolve for efficiency on large segments
    from scipy.signal import fftconvolve
    autocorr = fftconvolve(segment, segment[::-1], mode='full')
    autocorr = autocorr[n - 1:]  # Take positive lags only
    if autocorr[0] > 0:
        autocorr = autocorr / autocorr[0]  # Normalize
    else:
        return 20.0  # Degenerate signal

    # Search for peak in pitch range: 80-500 Hz
    # Lag for 500 Hz = sample_rate / 500, lag for 80 Hz = sample_rate / 80
    min_lag = max(1, int(sample_rate / 500))
    max_lag = min(len(autocorr) - 1, int(sample_rate / 80))

    if min_lag >= max_lag or max_lag >= len(autocorr):
        return 20.0  # Can't search pitch range

    search_region = autocorr[min_lag:max_lag + 1]
    if len(search_region) == 0:
        return 20.0

    r_peak = float(np.max(search_region))

    # Clamp to valid range for log computation
    # r_peak must be in (0, 1) for the formula to work
    if r_peak >= 1.0:
        return 40.0  # Nearly perfect harmonic (pure tone)
    if r_peak <= 0.0:
        return -10.0  # Pure noise

    # HNR = 10 * log10(r / (1 - r))
    import math
    hnr = 10.0 * math.log10(r_peak / (1.0 - r_peak))
    return round(hnr, 2)


def compute_zcr(audio_segment, sample_rate=16000):
    """Compute Zero-Crossing Rate from raw audio waveform.

    ZCR counts how often the waveform crosses zero per second (Hz).
    Matches the Praat PointProcess(zeroes) methodology from Zhang et al.

    Speech has moderate ZCR (~1500-3000 Hz). Sighs and throat-clearing
    have LOW ZCR (<1500 Hz) because they're aperiodic broadband noise
    without rapid oscillation. Laughter has higher ZCR due to harmonic
    structure. This distinguishes insertion-prone events (sigh/throat-clear)
    from substitution-prone events (laughter).

    Returns ZCR in Hz. Returns 2000.0 (safe default = "assume speech")
    for degenerate inputs.
    """
    import numpy as np

    if len(audio_segment) < 100:
        return 2000.0  # Too short to analyze

    # Remove DC offset
    segment = audio_segment - np.mean(audio_segment)

    # Count sign changes in the waveform
    signs = np.sign(segment)
    # Remove zeros (treat as positive to avoid double-counting)
    signs[signs == 0] = 1
    crossings = np.sum(np.abs(np.diff(signs)) > 0)

    duration = len(audio_segment) / sample_rate
    if duration <= 0:
        return 2000.0

    zcr = crossings / duration
    return round(zcr, 1)


def compute_log_energy(audio_segment):
    """Compute log energy of audio segment in dB.

    Used for Gupta-style energy-based filtering: discard events
    below -35 dB (too quiet to be meaningful paralinguistic events).
    Also discriminates high-energy events (gasp, sneeze) from
    low-energy events (sigh, breathing).

    Returns energy in dB. Returns -60.0 for silence.
    """
    import numpy as np

    if len(audio_segment) < 10:
        return -60.0

    rms = float(np.sqrt(np.mean(audio_segment.astype(float) ** 2)))
    if rms < 1e-10:
        return -60.0

    import math
    return round(20.0 * math.log10(rms), 1)


def _classify_from_error_patterns(whisper_low_conf, whisper_disagreements,
                                   wer_sdi=None):
    """Classify paralinguistic event type from Whisper error signatures.

    Uses Zhang's finding: error-type composition predicts event type.
    - Substitution + Deletion clusters → Laughter (48.9% S + 39.1% D)
    - Insertion clusters → Sigh (10.57x) or Throat-clearing (5.86x)
    - High no_speech_prob → Breathing or Pause

    Args:
        whisper_low_conf: low-confidence segments from Whisper
        whisper_disagreements: multi-temp voting disagreements
        wer_sdi: optional (substitutions, deletions, insertions) tuple from compute_wer

    Returns list of candidate events:
        [{type, start_s, confidence, detection_method}]
    """
    candidates = []

    # Signal 1: Error-type signature from WER decomposition
    if wer_sdi and sum(wer_sdi) > 0:
        subs, dels, ins = wer_sdi
        total_errors = subs + dels + ins
        sd_ratio = (subs + dels) / total_errors
        ins_ratio = ins / total_errors

        if sd_ratio >= _LAUGHTER_SD_RATIO and total_errors >= 2:
            candidates.append({
                "type": "Laughter",
                "confidence": min(0.9, 0.4 + sd_ratio * 0.5),
                "detection_method": "error_pattern_sd",
                "detail": f"S={subs} D={dels} I={ins} sd_ratio={sd_ratio:.2f}"
            })
        elif ins_ratio >= _INSERTION_RATIO and total_errors >= 2:
            # Sigh vs throat-clearing: sighs cause before-event errors,
            # throat-clearing causes during-event errors.
            # Without precise timing, use insertion density as tiebreaker:
            # higher insertion density = throat-clearing (40% insertions)
            if ins_ratio >= 0.45:
                candidates.append({
                    "type": "Throat-clearing",
                    "confidence": min(0.85, 0.3 + ins_ratio * 0.6),
                    "detection_method": "error_pattern_ins_high",
                    "detail": f"S={subs} D={dels} I={ins} ins_ratio={ins_ratio:.2f}"
                })
            else:
                candidates.append({
                    "type": "Sigh",
                    "confidence": min(0.8, 0.3 + ins_ratio * 0.5),
                    "detection_method": "error_pattern_ins",
                    "detail": f"S={subs} D={dels} I={ins} ins_ratio={ins_ratio:.2f}"
                })

    # Signal 2: High no_speech_prob segments → breathing or pause
    if whisper_low_conf:
        for seg in whisper_low_conf:
            if seg.get("block_suspect"):
                no_speech = seg.get("no_speech_prob", 0)
                avg_lp = seg.get("avg_logprob", 0)
                # Very high no_speech_prob + very low logprob = breathing/pause
                if no_speech > 0.5:
                    event_type = "Breathing" if no_speech > 0.7 else "Pause"
                    candidates.append({
                        "type": event_type,
                        "confidence": min(0.9, no_speech * 0.8),
                        "detection_method": "no_speech_prob",
                        "detail": f"no_speech={no_speech:.2f} logprob={avg_lp:.2f}",
                        "text": seg.get("text", ""),
                    })

    # Signal 3: Multi-temp disagreement density
    # Dense disagreements in a small window = audio is non-speech
    if whisper_disagreements and len(whisper_disagreements) >= 3:
        # Cluster disagreements by position proximity
        positions = [d["position"] for d in whisper_disagreements]
        if len(positions) >= 3:
            # Check if disagreements are clustered (within 5 word positions)
            for i in range(len(positions) - 2):
                window = positions[i:i+3]
                if window[-1] - window[0] <= 5:
                    candidates.append({
                        "type": "unknown",  # Needs HNR to classify
                        "confidence": min(0.7, 0.2 + len(whisper_disagreements) * 0.1),
                        "detection_method": "disagreement_cluster",
                        "detail": f"{len(whisper_disagreements)} disagreements, cluster at pos {window[0]}-{window[-1]}",
                    })
                    break  # One cluster candidate is enough

    return candidates


def detect_paralinguistic_events(audio_data, sample_rate, whisper_segments,
                                  whisper_low_conf, whisper_disagreements,
                                  wer_sdi=None):
    """Main Layer 5 detection: find paralinguistic events in audio.

    Combines multiple signals:
    1. Error-type patterns from Whisper metadata (zero-cost, already computed)
    2. HNR analysis on candidate windows (numpy/scipy, ~5ms per window)
    3. Temporal gating (discard events < 500ms, laughter < 1000ms)

    The ±1s rule (Zhang): 96.1% of ASR errors cluster within 1s of a
    paralinguistic event. We use Whisper error locations to find candidate
    windows, then analyze the raw audio in those windows.

    Args:
        audio_data: numpy array of audio samples
        sample_rate: sample rate (typically 16000)
        whisper_segments: Whisper verbose JSON segments
        whisper_low_conf: low-confidence segments from _extract_low_confidence_segments
        whisper_disagreements: multi-temp voting disagreements
        wer_sdi: optional (substitutions, deletions, insertions) tuple

    Returns list of detected events:
        [{type, start_s, end_s, confidence, detection_method, hnr_db}]
    """
    import numpy as np

    total_duration = len(audio_data) / sample_rate if sample_rate > 0 else 0
    if total_duration < 0.5:
        return []  # Audio too short for meaningful detection

    events = []

    # Step 1: Get candidate events from error patterns
    candidates = _classify_from_error_patterns(
        whisper_low_conf, whisper_disagreements, wer_sdi
    )

    # Step 2: For each candidate, find the audio window and compute HNR
    # Use Whisper segment timestamps to locate the candidate in audio
    segment_times = []
    if whisper_segments:
        for seg in whisper_segments:
            start = seg.get("start", 0)
            end = seg.get("end", start + 1)
            segment_times.append((start, end))

    for cand in candidates:
        # Determine the audio window for this candidate
        # Default: analyze the full audio if we can't localize
        window_start_s = 0.0
        window_end_s = total_duration

        # Try to localize from low-confidence segment text
        if cand.get("text") and segment_times:
            for seg, (seg_start, seg_end) in zip(whisper_segments, segment_times):
                if cand["text"] in seg.get("text", ""):
                    # Apply +-1s window (Zhang's temporal error zone)
                    window_start_s = max(0, seg_start - _EVENT_WINDOW_S)
                    window_end_s = min(total_duration, seg_end + _EVENT_WINDOW_S)
                    break

        # Extract audio window
        start_sample = int(window_start_s * sample_rate)
        end_sample = min(len(audio_data), int(window_end_s * sample_rate))
        if end_sample - start_sample < int(sample_rate * 0.05):  # < 50ms
            continue

        audio_window = audio_data[start_sample:end_sample]

        # Compute acoustic features on the window
        hnr = compute_hnr(audio_window, sample_rate)
        zcr = compute_zcr(audio_window, sample_rate)
        energy_db = compute_log_energy(audio_window)

        # NVS-38K energy floor: discard events below -35 dB
        if energy_db < _ENERGY_FLOOR_DB:
            continue

        event_duration = window_end_s - window_start_s

        # Decision: HNR < 4.0 dB confirms paralinguistic event
        if hnr < _HNR_SPEECH_THRESHOLD:
            # Boost confidence based on how low the HNR is
            hnr_boost = min(0.3, (_HNR_SPEECH_THRESHOLD - hnr) * 0.05)
            # Boost from ZCR agreement: low ZCR + insertion errors = strong signal
            zcr_boost = 0.0
            if zcr < _ZCR_LOW_THRESHOLD and cand["detection_method"] in ("error_pattern_ins", "error_pattern_ins_high"):
                zcr_boost = 0.15  # ZCR confirms the insertion-based classification
            final_confidence = min(0.95, cand["confidence"] + hnr_boost + zcr_boost)

            # Gupta masking: aggressive suppression below T0
            if final_confidence < _GUPTA_T0:
                continue
            if final_confidence < _CONFIDENCE_FLOOR:
                continue

            # Classify unknown candidates using HNR + ZCR + energy + duration
            event_type = cand["type"]
            if event_type == "unknown":
                rms = float(np.sqrt(np.mean(audio_window.astype(float) ** 2)))

                if hnr < _HNR_CERTAIN_THRESHOLD and zcr > _ZCR_LOW_THRESHOLD:
                    # Very low HNR + high ZCR = impulsive voiced noise
                    if rms > 0.15:
                        event_type = "Sneezing"
                    else:
                        event_type = "Cough"
                elif hnr < _HNR_CERTAIN_THRESHOLD and zcr < _ZCR_NASAL_THRESHOLD and event_duration < 0.8:
                    # Very low HNR + very low ZCR + short = nasal burst
                    event_type = "Sniff"
                elif energy_db > -15.0 and event_duration < 0.6 and zcr > 2000:
                    # Sudden high energy + short + high ZCR = gasp (sudden air intake)
                    event_type = "Gasp"
                elif event_duration >= _MIN_YAWNING_DURATION_S and rms < 0.03:
                    # Long, breathy, low energy = yawning
                    event_type = "Yawning"
                elif hnr >= 2.5 and hnr < _HNR_SPEECH_THRESHOLD and rms > 0.05:
                    # Partially voiced + moderate energy + irregular = crying
                    event_type = "Crying"
                elif zcr < _ZCR_LOW_THRESHOLD:
                    # Low ZCR = aperiodic broadband = sigh
                    event_type = "Sigh"
                else:
                    event_type = "Sigh"  # Default fallback for unclassifiable low-HNR

            # Refine existing classifications using ZCR
            # If error patterns said "Sigh" but ZCR is very low + short duration = could be Sniff
            if event_type == "Sigh" and zcr < _ZCR_NASAL_THRESHOLD and event_duration < 0.8:
                event_type = "Sniff"

            # Apply duration gates
            if event_type == "Laughter" and event_duration < _MIN_LAUGHTER_DURATION_S:
                continue
            elif event_type == "Yawning" and event_duration < _MIN_YAWNING_DURATION_S:
                continue
            elif event_type == "Crying" and event_duration < _MIN_CRYING_DURATION_S:
                continue
            elif event_type == "Sniff" and event_duration < _MIN_SNIFF_DURATION_S:
                continue
            elif event_type == "Gasp" and event_duration < _MIN_GASP_DURATION_S:
                continue
            elif event_duration < _MIN_EVENT_DURATION_S:
                continue

            # Gupta T1 gate: only commit high-confidence events to transcript
            # Events between T0 and T1 are logged but not tagged
            committed = final_confidence >= _GUPTA_T1

            events.append({
                "type": event_type,
                "start_s": round(window_start_s, 2),
                "end_s": round(window_end_s, 2),
                "confidence": round(final_confidence, 2),
                "detection_method": cand["detection_method"],
                "hnr_db": hnr,
                "zcr_hz": zcr,
                "energy_db": energy_db,
                "committed": committed,
            })
        elif hnr >= _HNR_SPEECH_THRESHOLD and cand["type"] in ("Pause", "Breathing"):
            # Pause/Breathing can still be valid even with higher HNR
            # (silence has no meaningful HNR; breathing can be slightly harmonic)
            if cand["confidence"] >= 0.5:
                event_duration = window_end_s - window_start_s
                if event_duration >= _MIN_EVENT_DURATION_S:
                    events.append({
                        "type": cand["type"],
                        "start_s": round(window_start_s, 2),
                        "end_s": round(window_end_s, 2),
                        "confidence": round(cand["confidence"], 2),
                        "detection_method": cand["detection_method"],
                        "hnr_db": hnr,
                    })

    return events


def format_paralinguistic_tags(events):
    """Format detected events as inline transcript tags.

    Sorted by start time. Only includes events with valid tag types.
    Only includes committed events (passed Gupta T1 threshold).
    """
    tags = []
    for ev in sorted(events, key=lambda e: e.get("start_s", 0)):
        if ev["type"] in PARALINGUISTIC_TAGS:
            tags.append(f"[{ev['type']}]")
    return tags


def inject_paralinguistic_tags_tsa(text, events, whisper_segments):
    """Temporal-Semantic Alignment (TSA) tag injection.

    Instead of appending tags at the end of the transcript, this function
    injects each paralinguistic tag at the correct word boundary based on
    timestamp alignment between the event and Whisper's word-level output.

    Algorithm (from NVSpeech-38K / TSA method):
    1. Build a word-timestamp map from Whisper segments
    2. For each committed paralinguistic event, find the nearest word
       boundary by comparing event start_s to word timestamps
    3. Insert the tag after the nearest preceding word
    4. If event is >1.0s from any word boundary, discard it (noise)

    Also applies regex cleanup for fused tokens (Trouvain speech-laugh
    artifact): if Whisper produced "yeah[Laughter]" as one token, split
    it into "yeah [Laughter]".

    Args:
        text: the transcript string to inject tags into
        events: list of detected paralinguistic events (from detect_paralinguistic_events)
        whisper_segments: Whisper verbose JSON segments with word timestamps

    Returns:
        text with tags injected at correct positions, or original text if
        no committed events or no timestamp data available.
    """
    import re

    # Filter to committed events only (passed Gupta T1 threshold)
    committed = [e for e in events if e.get("committed", False) and e["type"] in PARALINGUISTIC_TAGS]
    if not committed:
        return text

    # Build word-timestamp list from Whisper segments
    word_times = []
    if whisper_segments:
        for seg in whisper_segments:
            words = seg.get("words", [])
            for w in words:
                word_times.append({
                    "word": w.get("word", "").strip(),
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                })

    # If no word-level timestamps, fall back to end-append
    if not word_times:
        tags = [f"[{e['type']}]" for e in sorted(committed, key=lambda e: e.get("start_s", 0))]
        return text.rstrip() + " " + " ".join(tags) if tags else text

    # Split text into words, preserving positions for reconstruction
    text_words = text.split()
    if not text_words:
        return text

    # For each committed event, find the insertion point
    # Sort events by start time to process in order
    insertions = {}  # word_index -> list of tags to insert after it
    for ev in sorted(committed, key=lambda e: e.get("start_s", 0)):
        ev_start = ev.get("start_s", 0)
        tag = f"[{ev['type']}]"

        # Find the nearest word boundary
        best_idx = -1
        best_dist = float('inf')
        for i, wt in enumerate(word_times):
            # Distance from event start to word end (insert after the word)
            dist = abs(ev_start - wt["end"])
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        # 1-second discard rule: if event is too far from any word, skip
        if best_dist > 1.0:
            continue

        # Map word_times index to text_words index
        # word_times and text_words should be roughly aligned
        insert_after = min(best_idx, len(text_words) - 1)
        if insert_after not in insertions:
            insertions[insert_after] = []
        insertions[insert_after].append(tag)

    # Reconstruct text with injected tags
    if not insertions:
        return text

    result_parts = []
    for i, word in enumerate(text_words):
        result_parts.append(word)
        if i in insertions:
            result_parts.extend(insertions[i])

    result = " ".join(result_parts)

    # Regex cleanup for fused tokens (Trouvain speech-laugh artifact)
    # e.g., "yeah[Laughter]" -> "yeah [Laughter]"
    result = re.sub(r'(\w)(\[(?:' + '|'.join(PARALINGUISTIC_TAGS) + r')\])', r'\1 \2', result)
    # e.g., "[Laughter]yeah" -> "[Laughter] yeah"
    result = re.sub(r'(\[(?:' + '|'.join(PARALINGUISTIC_TAGS) + r')\])(\w)', r'\1 \2', result)

    return result


# -- Layer 5.5: Prosodic Bridging ────────────────────────────────
# Per-segment extraction of prosodic features that Whisper's text decoder
# destroys: F0 (pitch), energy, speaking rate, pitch direction.
# Two papers drive this:
#   USDM (Kim et al., NeurIPS 2024): acoustic tokens preserve prosodic info
#   SpeechEmotionLlama (Kang et al., Interspeech 2025): frozen LLMs respond
#   to text-described paralinguistic state — even a crude <happy> tag helps.
# We extract what Whisper destroys and describe it as structured text for GPT.

_last_prosodic_features = []
_last_speaker_state = ""


def extract_f0(audio_segment, sample_rate=16000):
    """Extract fundamental frequency (F0) via autocorrelation.

    Same math as compute_hnr() but returns the frequency at the
    autocorrelation peak instead of the peak-to-noise ratio.
    Returns F0 in Hz, or 0.0 if no pitch detected (unvoiced/noise).
    """
    import numpy as np
    from scipy.signal import fftconvolve

    min_samples = int(sample_rate / 80) * 2
    if len(audio_segment) < min_samples:
        return 0.0

    segment = audio_segment - np.mean(audio_segment)
    rms = np.sqrt(np.mean(segment ** 2))
    if rms < 1e-6:
        return 0.0

    autocorr = fftconvolve(segment, segment[::-1], mode='full')
    autocorr = autocorr[len(segment) - 1:]
    if autocorr[0] <= 0:
        return 0.0
    autocorr = autocorr / autocorr[0]

    min_lag = max(1, int(sample_rate / 500))
    max_lag = min(len(autocorr) - 1, int(sample_rate / 80))
    if min_lag >= max_lag:
        return 0.0

    search = autocorr[min_lag:max_lag + 1]
    if len(search) == 0:
        return 0.0

    peak_val = float(np.max(search))
    if peak_val < 0.2:  # Too weak — not a clear pitch
        return 0.0

    peak_lag = int(np.argmax(search)) + min_lag
    if peak_lag == 0:
        return 0.0

    return round(sample_rate / peak_lag, 1)


def extract_prosodic_features(audio_data, whisper_segments, sample_rate=16000):
    """Extract per-segment prosodic features from raw audio.

    For each Whisper segment, computes:
      - f0_mean: mean fundamental frequency (Hz)
      - f0_var: F0 variance across sub-windows (pitch stability)
      - energy: RMS energy of the segment
      - rate_sps: speaking rate (syllables per second, estimated from word count)
      - pitch_direction: rising / falling / flat / erratic
      - hnr: Harmonics-to-Noise Ratio (reused from Layer 5)

    Uses autocorrelation (same pattern as compute_hnr/extract_f0).
    Numpy/scipy only. No new dependencies.

    Returns list of dicts with timestamps, one per segment.
    """
    import numpy as np

    total_duration = len(audio_data) / sample_rate if sample_rate > 0 else 0
    if total_duration < 0.3 or not whisper_segments:
        return []

    features = []
    for seg in whisper_segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", seg_start + 0.5)
        seg_text = seg.get("text", "").strip()
        seg_duration = max(seg_end - seg_start, 0.01)

        # Extract audio window for this segment
        start_sample = max(0, int(seg_start * sample_rate))
        end_sample = min(len(audio_data), int(seg_end * sample_rate))
        if end_sample - start_sample < int(sample_rate * 0.05):
            features.append({
                "start_s": round(seg_start, 2), "end_s": round(seg_end, 2),
                "text": seg_text, "f0_mean": 0.0, "f0_var": 0.0,
                "energy": 0.0, "rate_sps": 0.0, "pitch_direction": "flat",
                "hnr": 20.0,
            })
            continue

        window = audio_data[start_sample:end_sample]

        # RMS energy
        energy = float(np.sqrt(np.mean(window ** 2)))

        # HNR
        hnr = compute_hnr(window, sample_rate)

        # F0: split segment into 3-4 sub-windows for contour
        n_subwindows = min(4, max(2, int(seg_duration / 0.1)))
        sub_len = len(window) // n_subwindows
        f0_values = []
        for i in range(n_subwindows):
            sub = window[i * sub_len:(i + 1) * sub_len]
            if len(sub) >= int(sample_rate / 80) * 2:
                f0 = extract_f0(sub, sample_rate)
                if f0 > 0:
                    f0_values.append(f0)

        f0_mean = round(float(np.mean(f0_values)), 1) if f0_values else 0.0
        f0_var = round(float(np.var(f0_values)), 1) if len(f0_values) >= 2 else 0.0

        # Pitch direction from F0 contour slope
        if len(f0_values) >= 2:
            slope = f0_values[-1] - f0_values[0]
            f0_range = max(f0_values) - min(f0_values)
            if f0_range > f0_mean * 0.3 and f0_var > 100:
                pitch_dir = "erratic"
            elif slope > f0_mean * 0.1:
                pitch_dir = "rising"
            elif slope < -f0_mean * 0.1:
                pitch_dir = "falling"
            else:
                pitch_dir = "flat"
        else:
            pitch_dir = "flat"

        # Speaking rate: word count / duration
        word_count = len(seg_text.split()) if seg_text else 0
        # Rough syllable estimate: ~1.3 syllables per word (English average)
        syllables = word_count * 1.3
        rate_sps = round(syllables / seg_duration, 1) if seg_duration > 0.1 else 0.0

        features.append({
            "start_s": round(seg_start, 2),
            "end_s": round(seg_end, 2),
            "text": seg_text,
            "f0_mean": f0_mean,
            "f0_var": f0_var,
            "energy": round(energy, 4),
            "rate_sps": rate_sps,
            "pitch_direction": pitch_dir,
            "hnr": hnr,
        })

    return features


def compute_speaker_baseline(prof, db_sessions_func, limit=50):
    """Compute prosodic baseline from historical sessions.

    Pulls stored prosodic summaries and computes running averages
    for F0, energy, and speaking rate. Stores in profile under
    prosodic_baseline key. Returns baseline dict with means and stds.
    """
    import numpy as np

    baseline = prof.get("prosodic_baseline", {
        "f0_mean": 0.0, "f0_std": 1.0,
        "energy_mean": 0.0, "energy_std": 1.0,
        "rate_mean": 0.0, "rate_std": 1.0,
        "n_sessions": 0,
    })

    # Pull recent sessions that have prosodic summaries
    try:
        sessions = db_sessions_func(limit=limit)
    except Exception:
        return baseline

    f0_vals, energy_vals, rate_vals = [], [], []
    for s in sessions:
        ps = s.get("prosodic_summary")
        if isinstance(ps, str):
            try:
                ps = json.loads(ps)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(ps, dict):
            continue
        if ps.get("f0_mean", 0) > 0:
            f0_vals.append(ps["f0_mean"])
        if ps.get("energy_mean", 0) > 0:
            energy_vals.append(ps["energy_mean"])
        if ps.get("rate_mean", 0) > 0:
            rate_vals.append(ps["rate_mean"])

    if len(f0_vals) >= 3:
        baseline["f0_mean"] = round(float(np.mean(f0_vals)), 1)
        baseline["f0_std"] = round(max(float(np.std(f0_vals)), 1.0), 1)
    if len(energy_vals) >= 3:
        baseline["energy_mean"] = round(float(np.mean(energy_vals)), 4)
        baseline["energy_std"] = round(max(float(np.std(energy_vals)), 0.0001), 4)
    if len(rate_vals) >= 3:
        baseline["rate_mean"] = round(float(np.mean(rate_vals)), 1)
        baseline["rate_std"] = round(max(float(np.std(rate_vals)), 0.1), 1)
    baseline["n_sessions"] = len(f0_vals)

    return baseline


def infer_speaker_state(prosodic_features, baseline):
    """Map prosodic deviations to a natural language state description.

    Compares current session features against personal baseline.
    Returns a descriptive sentence, not a label.

    Deviation rules (from USDM + SpeechEmotionLlama findings):
      High F0 var + fast rate + high energy = elevated arousal/stress
      Dropping energy + slow rate = fatigue/shutdown
      Erratic F0 near a block = vocal fold tension
      Stable features = calm/casual
    """
    if not prosodic_features:
        return ""

    import numpy as np

    # Compute session-level averages
    f0s = [f["f0_mean"] for f in prosodic_features if f["f0_mean"] > 0]
    energies = [f["energy"] for f in prosodic_features if f["energy"] > 0]
    rates = [f["rate_sps"] for f in prosodic_features if f["rate_sps"] > 0]
    f0_vars = [f["f0_var"] for f in prosodic_features if f["f0_var"] > 0]
    pitch_dirs = [f["pitch_direction"] for f in prosodic_features]

    if not f0s and not energies:
        return ""

    sess_f0 = float(np.mean(f0s)) if f0s else 0
    sess_energy = float(np.mean(energies)) if energies else 0
    sess_rate = float(np.mean(rates)) if rates else 0
    sess_f0_var = float(np.mean(f0_vars)) if f0_vars else 0
    erratic_ratio = pitch_dirs.count("erratic") / max(len(pitch_dirs), 1)

    # Compute deviations from baseline in sigma units
    b = baseline
    f0_dev = (sess_f0 - b["f0_mean"]) / b["f0_std"] if b["f0_std"] > 0 and b["f0_mean"] > 0 else 0
    energy_dev = (sess_energy - b["energy_mean"]) / b["energy_std"] if b["energy_std"] > 0 and b["energy_mean"] > 0 else 0
    rate_dev = (sess_rate - b["rate_mean"]) / b["rate_std"] if b["rate_std"] > 0 and b["rate_mean"] > 0 else 0

    # State inference rules
    parts = []

    # High arousal: elevated F0 variance + fast rate + high energy
    if (sess_f0_var > 200 or f0_dev > 1.5) and rate_dev > 0.5 and energy_dev > 0.5:
        parts.append(f"Elevated stress/arousal (F0 {f0_dev:+.1f}σ, energy {energy_dev:+.1f}σ, rate {rate_dev:+.1f}σ)")

    # Fatigue/shutdown: dropping energy + slow rate
    elif energy_dev < -1.0 and rate_dev < -0.5:
        parts.append(f"Low energy/fatigue (energy {energy_dev:+.1f}σ, rate {rate_dev:+.1f}σ)")

    # Erratic pitch = vocal tension (often near blocks)
    elif erratic_ratio > 0.3:
        parts.append(f"Vocal tension (erratic pitch in {erratic_ratio:.0%} of segments)")

    # Amused/laughing: high energy + high F0 variance + erratic
    elif energy_dev > 0.5 and sess_f0_var > 150:
        parts.append(f"Amused/animated (F0 variance elevated, energy {energy_dev:+.1f}σ)")

    # Calm/casual: everything near baseline
    elif abs(f0_dev) < 1.0 and abs(energy_dev) < 1.0 and abs(rate_dev) < 1.0:
        parts.append("Calm/casual (features near baseline)")

    # Mild deviation — note it but don't over-interpret
    else:
        deviations = []
        if abs(f0_dev) > 1.0:
            deviations.append(f"F0 {f0_dev:+.1f}σ")
        if abs(energy_dev) > 1.0:
            deviations.append(f"energy {energy_dev:+.1f}σ")
        if abs(rate_dev) > 1.0:
            deviations.append(f"rate {rate_dev:+.1f}σ")
        if deviations:
            parts.append(f"Mild deviation ({', '.join(deviations)})")

    # Situation inference suggestion
    suggestion = ""
    if f0_dev > 1.5 and energy_dev > 1.0:
        suggestion = "auto_suggest: situation may warrant upgrade (elevated prosodic stress)"

    state = "; ".join(parts) if parts else "Neutral"
    return state + (f" [{suggestion}]" if suggestion else "")


def build_prosodic_context(prosodic_features, paralinguistic_events, speaker_state):
    """Format a per-segment prosodic transcript for prompt injection.

    Combines Layer 5 event tags with per-segment F0/energy/rate annotations.
    Includes stutter-specific prosodic rules derived from USDM + Kang findings.
    """
    if not prosodic_features:
        return ""

    lines = ["PROSODIC CONTEXT (acoustic features Whisper cannot transcribe):"]

    # Build a map of paralinguistic events by time for overlay
    event_map = {}
    for ev in (paralinguistic_events or []):
        event_map[(ev.get("start_s", 0), ev.get("end_s", 0))] = ev

    for feat in prosodic_features[:15]:  # Cap at 15 segments
        start = feat["start_s"]
        end = feat["end_s"]
        text = feat.get("text", "")

        # Check for overlapping paralinguistic event
        para_tag = ""
        for (ev_start, ev_end), ev in event_map.items():
            if ev_start <= end and ev_end >= start:
                para_tag = f" [{ev['type']}] HNR:{ev.get('hnr_db', '?')}dB —"
                break

        # Format segment annotation
        f0_str = f"pitch:{feat['pitch_direction']}" if feat["f0_mean"] > 0 else "pitch:none"
        energy_label = "high" if feat["energy"] > 0.1 else "low" if feat["energy"] < 0.02 else "moderate"
        rate_str = f"rate:{feat['rate_sps']}syl/s" if feat["rate_sps"] > 0 else "rate:0"

        if para_tag:
            lines.append(f"  [{start:.1f}-{end:.1f}s]{para_tag} non-speech, DISCARD Whisper text")
        elif text:
            lines.append(f"  [{start:.1f}-{end:.1f}s] {f0_str} energy:{energy_label} {rate_str}")
        else:
            lines.append(f"  [{start:.1f}-{end:.1f}s] {f0_str} energy:{energy_label} — silence/gap")

    if speaker_state:
        lines.append(f"SPEAKER STATE: {speaker_state}")

    # Stutter-specific prosodic reconstruction rules
    lines.append(
        "\nSTUTTER-PROSODIC RULES (use acoustic context to disambiguate):"
        "\n- Block + laughter context = self-deprecating humor → reconstruct lightly, preserve tone"
        "\n- Block + dropping energy = frustration/shutdown → reconstruct gently"
        "\n- Repetition + rising pitch = genuine struggle → aggressive reconstruction"
        "\n- Repetition + stable pitch = emphatic repetition, NOT a stutter → leave it"
        "\n- Filler + flat energy + constant pitch = postponement stalling → strip it"
        "\n- Filler + rising pitch = discourse marker ('you know?') → keep it"
    )

    return "\n".join(lines)


def compute_prosodic_summary(prosodic_features):
    """Compute session-level prosodic summary for logging.

    Returns dict with f0_mean, energy_mean, rate_mean, speaker_state_label.
    Stored in sessions table for long-term trend tracking.
    """
    import numpy as np

    if not prosodic_features:
        return None

    f0s = [f["f0_mean"] for f in prosodic_features if f["f0_mean"] > 0]
    energies = [f["energy"] for f in prosodic_features if f["energy"] > 0]
    rates = [f["rate_sps"] for f in prosodic_features if f["rate_sps"] > 0]
    pitch_dirs = [f["pitch_direction"] for f in prosodic_features]

    return {
        "f0_mean": round(float(np.mean(f0s)), 1) if f0s else 0.0,
        "f0_var": round(float(np.var(f0s)), 1) if len(f0s) >= 2 else 0.0,
        "energy_mean": round(float(np.mean(energies)), 4) if energies else 0.0,
        "rate_mean": round(float(np.mean(rates)), 1) if rates else 0.0,
        "n_segments": len(prosodic_features),
        "pitch_directions": {d: pitch_dirs.count(d) for d in set(pitch_dirs)},
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

    # Audio preprocessing: DC removal → high-pass filter → AGC → soft clip
    # Quiet Mode: aggressive gain for whispered/soft speech, tighter high-pass to kill room noise
    hp_cutoff = 100.0 if quiet_mode_enabled else 70.0
    agc_target_db = -6 if quiet_mode_enabled else -12
    # 1. DC offset removal — centers waveform around zero
    audio_data = audio_data - numpy.mean(audio_data)
    # 2. High-pass filter — removes AC hum, desk vibrations, wind rumble
    #    Butterworth order 2 is gentle enough to preserve speech fundamentals
    #    Quiet mode uses 100Hz (tighter) since whispers have no low-freq content anyway
    nyq = TARGET_RATE / 2.0
    b_hp, a_hp = butter(2, hp_cutoff / nyq, btype="highpass")
    audio_data = filtfilt(b_hp, a_hp, audio_data).astype(numpy.float32)
    # 3. AGC: normalize RMS so Whisper gets consistent input levels
    #    Normal: -12dB, Quiet mode: -6dB (double the gain for whispered speech)
    rms = numpy.sqrt(numpy.mean(audio_data ** 2))
    if rms > 1e-6:
        target_rms = 10 ** (agc_target_db / 20)
        audio_data = audio_data * (target_rms / rms)
    # 4. Soft clip via tanh — gentler than hard clip, avoids digital artifacts
    #    in Whisper's mel spectrogram from peak transients
    audio_data = numpy.tanh(1.2 * audio_data).astype(numpy.float32)

    # Step 0: Speech rate & pause analysis — pure numpy, ~2ms, feeds reconstruction severity at L2+
    speech_metrics = {"pause_ratio": 0, "speaking_rate_sps": 0, "severity_modifier": 0}
    if current_layer >= 2:
        speech_metrics = analyze_speech_rate(audio_data, TARGET_RATE)
        if speech_metrics["severity_modifier"] > 0:
            log(f"Speech: pause_ratio={speech_metrics['pause_ratio']:.0%} rate={speech_metrics['speaking_rate_sps']:.1f}syl/s → severity +{speech_metrics['severity_modifier']}", "info")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_data, TARGET_RATE)
    tmp.close()

    try:
        # Step 1: Whisper (enhanced — Script Prep seeding + verbose JSON + multi-temp voting)
        t0 = time.time()
        whisper_result = whisper_transcribe(tmp.name)
        raw_text = whisper_result["text"].strip()
        whisper_segments = whisper_result["segments"]
        whisper_low_conf = whisper_result["low_confidence"]
        whisper_disagreements = whisper_result["disagreements"]
        whisper_meta = whisper_result["whisper_meta"]
        # Cache low-confidence segments + avg_logprob for dashboard
        global _last_low_conf_segments, _last_avg_logprob
        _last_low_conf_segments = whisper_low_conf or []
        if whisper_segments:
            # Filter out None — Moonshine segments have avg_logprob=None because
            # the ONNX decoder doesn't surface per-segment confidence. "in s"
            # check alone passes (key is present) but sum() on Nones crashes.
            logprobs = [s["avg_logprob"] for s in whisper_segments if s.get("avg_logprob") is not None]
            _last_avg_logprob = round(sum(logprobs) / len(logprobs), 3) if logprobs else 0.0
        else:
            _last_avg_logprob = 0.0
        t_asr = time.time()
        if not raw_text:
            state = 'idle'
            return

        # Log ASR pipeline details. The user-visible log doesn't name the
        # engine — it's an implementation detail that changes between
        # layers (Moonshine local at L1/L2/L3, cloud whisper-1 at L4).
        # Surfaces the prompt source + low-conf/disagreement signals only.
        used_local = (LOCAL_WHISPER and _local_transcribe_fn is not None) or whisper_meta['n_api_calls'] == 0
        source_label = "local" if used_local else f"{whisper_meta['n_api_calls']}calls"
        meta_tag = f"[{whisper_meta['prompt_source']}|{source_label}]"
        if whisper_low_conf:
            meta_tag += f" low_conf:{len(whisper_low_conf)}"
        if whisper_disagreements:
            meta_tag += f" disagree:{len(whisper_disagreements)}"
        log(f"ASR {meta_tag}", "info")

        used_fallback = False
        clean_text = None
        falcon_ok = True
        t_recon = t_asr
        t_val = t_asr

        # Step 1.3: Paralinguistic event detection (numpy/scipy, no API)
        # Only runs when toggle is ON — skipped entirely when OFF for speed
        global _last_paralinguistic_events
        para_events = []
        if paralinguistic_enabled:
            para_events = detect_paralinguistic_events(
                audio_data, TARGET_RATE, whisper_segments,
                whisper_low_conf, whisper_disagreements
            )
            if para_events:
                tags = format_paralinguistic_tags(para_events)
                log(f"Paralinguistic: {', '.join(tags)} ({len(para_events)} events)", "info")
        _last_paralinguistic_events = para_events

        # Step 1.4: Prosodic feature extraction (numpy/scipy, no API)
        # Only runs when toggle is ON
        global _last_prosodic_features, _last_speaker_state
        prosodic_feats = None
        prosodic_ctx = ""
        _last_speaker_state = ""
        if prosodic_enabled:
            prosodic_feats = extract_prosodic_features(audio_data, whisper_segments, TARGET_RATE)
        _last_prosodic_features = prosodic_feats
        if prosodic_feats and prosodic_enabled:
            baseline = compute_speaker_baseline(profile, db_get_sessions)
            speaker_state = infer_speaker_state(prosodic_feats, baseline)
            _last_speaker_state = speaker_state
            prosodic_ctx = build_prosodic_context(prosodic_feats, para_events, speaker_state)
            if speaker_state:
                log(f"Prosodic: {speaker_state}", "info")
            # Auto-suggest situation upgrade if prosodic stress is elevated
            if "auto_suggest" in speaker_state:
                log(f"Situation suggestion: prosodic features suggest higher stress than '{current_situation}'", "info")

        # Step 1.4b: SileroVAD cross-reference — flag Whisper output that falls
        # in non-speech windows as hallucination. Whisper hallucinates 40.3% of the
        # time on silence (Barański et al., 2025). For stutterers, silence = blocks,
        # so we mark them rather than stripping blindly.
        # SileroVAD: LOG-ONLY mode — analyze speech/silence but don't strip yet.
        # Once threshold is tuned for stuttered speech, switch to active filtering.
        vad_segments = detect_speech_segments(audio_data, TARGET_RATE, threshold=0.5)
        if vad_segments:
            speech_segs = [s for s in vad_segments if s["is_speech"]]
            silence_segs = [s for s in vad_segments if not s["is_speech"]]
            if silence_segs:
                total_silence = sum(s["end_s"] - s["start_s"] for s in silence_segs)
                total_audio = audio_data.shape[0] / TARGET_RATE
                log(f"VAD: {len(speech_segs)} speech + {len(silence_segs)} silence ({total_silence:.1f}s/{total_audio:.1f}s)", "info")
                # Log what WOULD be stripped (for tuning), but don't actually strip
                if whisper_segments:
                    _, would_strip = vad_filter_whisper_segments(whisper_segments, vad_segments)
                    if would_strip:
                        texts = [b["whisper_text"] for b in would_strip if b["whisper_text"]]
                        if texts:
                            log(f"VAD: would strip (not stripping): {texts[:3]}", "info")

        # Step 1.5a: Strip Whisper training-data hallucinations (otter.ai credits,
        # "Thank you for watching", "Subscribe to my channel" etc.) — these leak
        # in during silence/low-SNR audio from YouTube auto-caption training data
        _pre_hall = raw_text
        raw_text = strip_whisper_hallucinations(raw_text)
        if raw_text != _pre_hall:
            log(f"Stripped Whisper hallucination: \"{_pre_hall[:80]}\" -> \"{raw_text[:80]}\"", "info")
        if not raw_text.strip():
            log("Entire output was Whisper hallucination — nothing to paste", "warn")
            set_state('idle')
            return
        # Step 1.5b: Disfluency post-filter (rule-based, zero cost)
        # At L1: this IS the output cleanup (no GPT reconstruction)
        # At L2+: pre-cleans Whisper output before sending to GPT
        filtered_text = strip_disfluencies(raw_text)

        # Block hallucination removal: strip phantom words Whisper invents during blocks
        # Runs at all layers — GPT shouldn't see Whisper's phantom words either
        filtered_text = strip_block_hallucinations(filtered_text, whisper_low_conf)
        # Profile corrections (vocabulary/corrections map): L2+ so GPT sees learned fixes
        if current_layer >= 2:
            filtered_text = apply_profile_corrections(filtered_text, profile)

        if filtered_text != raw_text and current_layer == 1:
            log(f"Filter: \"{raw_text}\" → \"{filtered_text}\"", "info")

        # Layer 1 polish — Haiku reads Moonshine output and fixes obvious errors.
        # Adds ~500ms–1s. No tone, no profile injection — just "fix obvious typos
        # / mishears / truncations." Runs only when Anthropic is configured.
        # Output replaces filtered_text so the paste reflects the corrected version.
        if current_layer == 1 and anthropic_client is not None and filtered_text.strip():
            try:
                _polish_t0 = time.time()
                _polish_msg = anthropic_client.messages.create(
                    model=FALCON_HAIKU_MODEL,
                    max_tokens=400,
                    messages=[{
                        "role": "user",
                        "content": (
                            "You are a quick proofreader for voice transcription output. "
                            "The text below came from a local speech-to-text engine and may contain: "
                            "wrong-word substitutions (homophones, similar-sounding words), "
                            "truncated sentences, missing punctuation, obvious mishears. "
                            "Your job: fix ONLY clear errors. Do NOT rewrite, do NOT change tone, "
                            "do NOT add or remove content. Preserve casual speech, profanity, slang. "
                            "Output ONLY the corrected text — no preamble, no explanation, no markdown.\n\n"
                            f"Text: {filtered_text}"
                        ),
                    }],
                )
                _polished = "".join(b.text for b in _polish_msg.content if getattr(b, "type", None) == "text").strip()
                if _polished:
                    if _polished != filtered_text:
                        # Character-level diff — word-level was lighting up
                        # whole tokens for tiny changes ("this," vs "this." or
                        # "you" vs "You" got flagged as full word swaps).
                        # Character diff highlights ONLY the chars that
                        # actually changed.
                        try:
                            import difflib as _dl, html as _html
                            _sm = _dl.SequenceMatcher(None, filtered_text, _polished)
                            _parts = []
                            for tag, i1, i2, j1, j2 in _sm.get_opcodes():
                                if tag == 'equal':
                                    _parts.append(_html.escape(filtered_text[i1:i2]))
                                elif tag == 'delete':
                                    _parts.append(f"<span class='diff-removed'>{_html.escape(filtered_text[i1:i2])}</span>")
                                elif tag == 'insert':
                                    _parts.append(f"<span class='diff-added'>{_html.escape(_polished[j1:j2])}</span>")
                                elif tag == 'replace':
                                    _parts.append(f"<span class='diff-removed'>{_html.escape(filtered_text[i1:i2])}</span>")
                                    _parts.append(f"<span class='diff-added'>{_html.escape(_polished[j1:j2])}</span>")
                            _diff_html = "".join(_parts)
                            log(f"L1 polish ({int((time.time()-_polish_t0)*1000)}ms): {_diff_html}", "polish")
                        except Exception:
                            log(f"L1 polish: \"{filtered_text}\" → \"{_polished}\" ({int((time.time()-_polish_t0)*1000)}ms)", "info")
                    filtered_text = _polished
                    stats_inc("anthropic_calls")
            except Exception as _e:
                log(f"L1 polish failed (using raw filtered): {_e}", "warn")

        if current_layer > 1 and current_mode != "RAW":
            log(f"Raw: \"{raw_text}\"", "raw")

            # Step 2: Reconstruct (using pre-cleaned text to reduce GPT noise)
            # Pass Whisper confidence data so L4 can target uncertain segments
            # Pass paralinguistic events so L5 can guide hallucination removal
            try:
                clean_text = None
                if is_authenticated():
                    # Signed in → route through backend (rules live server-side).
                    # Local API key is dev-only per product decision 2026-04-20.
                    clean_text, _backend_falcon, _backend_result = reconstruct_via_backend(
                        filtered_text, current_tone, current_layer, profile,
                        current_situation, current_mode,
                        whisper_low_conf=whisper_low_conf,
                        whisper_disagreements=whisper_disagreements,
                        speech_severity_mod=speech_metrics["severity_modifier"],
                        paralinguistic_events=para_events if paralinguistic_enabled else None,
                        prosodic_context=prosodic_ctx if prosodic_enabled else None,
                    )
                    if clean_text is not None and current_mode == "SAFE":
                        falcon_ok = _backend_falcon  # backend already ran Falcon
                    elif clean_text is None and API_KEY:
                        log("Backend unreachable — falling back to local API key", "info")
                        # clean_text stays None; drop through to the direct-OpenAI branch below

                if clean_text is None and API_KEY:
                    # Local API key path: either not signed in, or backend failed.
                    clean_text = reconstruct(
                        filtered_text, current_tone, current_layer, profile, current_situation,
                        whisper_low_conf=whisper_low_conf,
                        whisper_disagreements=whisper_disagreements,
                        speech_severity_mod=speech_metrics["severity_modifier"],
                        paralinguistic_events=para_events if paralinguistic_enabled else None,
                        prosodic_context=prosodic_ctx if prosodic_enabled else None
                    )

                if clean_text is None:
                    log("No backend auth and no local API key — using raw", "error")
                    used_fallback = True
            except Exception as e:
                log(f"Reconstruct failed ({e}) -- using raw", "error")
                used_fallback = True
            t_recon = time.time()

            # Step 2.5: Catch LLM hallucinations in reconstruction output.
            # Two defenses:
            # A) Pattern match: chatbot responses, system prompt fragments
            # B) Length explosion: reconstruction should SHORTEN, not expand.
            #    If output is 2.5x longer than input, GPT fabricated content.
            #    (The "hallucination of the millennium" was a full fabricated
            #    paragraph about GitHub/Whisper/README from a 5-word input.)
            if clean_text and not used_fallback:
                _recon_lower = clean_text.strip().lower()
                _LLM_LEAK_PATTERNS = [
                    "i'm sorry", "i apologize", "i didn't catch that",
                    "could you please clarify", "could you please repeat",
                    "could you say that again", "i'm not sure what you meant",
                    "please clarify", "please provide more context",
                    "i cannot assist", "i can't assist", "i can't help",
                    "as an ai", "as a language model",
                    "please ensure that you", "ensure that you construct",
                    "i'd be happy to help",
                    "no output", "identified as hallucinated", "hallucinated filler",
                    "no transcription", "unable to transcribe", "no speech detected",
                    "[no output", "[hallucin", "[unable to",
                ]
                _leak_detected = False
                for pattern in _LLM_LEAK_PATTERNS:
                    if _recon_lower.startswith(pattern) or pattern in _recon_lower:
                        log(f"LLM leak detected in reconstruction: \"{clean_text[:80]}\" -- using raw", "warn")
                        _leak_detected = True
                        break

                # Length explosion check: if GPT output is 2.5x longer than input,
                # it fabricated content instead of cleaning speech
                if not _leak_detected and len(filtered_text.split()) >= 3:
                    _len_ratio = len(clean_text.split()) / max(1, len(filtered_text.split()))
                    if _len_ratio > 2.5:
                        log(f"LLM length explosion: {len(filtered_text.split())}w -> {len(clean_text.split())}w ({_len_ratio:.1f}x) -- using raw", "warn")
                        _leak_detected = True

                if _leak_detected:
                    clean_text = filtered_text
                    used_fallback = True
                    stats_inc("llm_leaks")

            # Step 3: Falcon (SAFE mode only, skip if fallback)
            if current_mode == "SAFE" and clean_text and not used_fallback:
                if len(filtered_text.split()) <= 3:
                    falcon_ok = True
                    clean_text = filtered_text
                    log(f"Falcon: SKIPPED (short utterance -- {len(filtered_text.split())} words)", "info")
                elif _text_nearly_identical(raw_text, clean_text):
                    falcon_ok = True
                    log("Falcon: SKIPPED (text nearly identical -- no meaningful reconstruction)", "info")
                else:
                    try:
                        falcon_ok = falcon_validate(raw_text, clean_text, current_layer, current_tone)
                    except Exception:
                        falcon_ok = True
                    if not falcon_ok:
                        stats_inc("falcon_rejects")
                        log("Falcon: REJECTED -- using raw", "error")
            t_val = time.time()

        # Critical token retention: verify numbers, names, dollar amounts survived reconstruction
        if clean_text and not used_fallback:
            critical_lost = _check_critical_retention(filtered_text, clean_text)
            if critical_lost:
                log(f"Critical tokens lost in reconstruction: {critical_lost}", "warn")
                # Fall back to raw if names/numbers were destroyed
                falcon_ok = False

        # Decision
        risk_flags = compute_risk_flags(raw_text, clean_text, falcon_ok, used_fallback, current_layer)
        decision = make_decision(falcon_ok, current_layer, used_fallback, risk_flags)
        output = clean_text if (decision["decision"] == "paste_clean" and clean_text) else filtered_text
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
        model_tag = f" [{_last_recon_model}]" if _last_recon_model and current_layer > 1 and current_mode != "RAW" else ""
        log(f"{decision['decision']} | {timings['total_ms']}ms (asr:{timings['asr_ms']} recon:{timings['reconstruct_ms']} val:{timings['validate_ms']}){model_tag}{flags_tag}", "info")

        # Inject paralinguistic tags into output if transcribe toggle is ON
        if paralinguistic_transcribe and para_events:
            output = inject_paralinguistic_tags_tsa(output, para_events, whisper_segments)

        # Paste or hold
        if decision["decision"] == "hold":
            log("HELD — high-risk output not pasted", "error")
        else:
            stats_inc("words", wc)
            stats_inc("chars", len(output))
            stats_inc("sessions")
            paste(output)
        # Stutter analytics: L4+ only — these are clinical metrics, not needed for basic transcription/rewrite
        disf_counts = {}
        exposure = {"score": 0, "band": "none", "components": {}}
        edit_dist = {}
        shadow_result = None
        covert_pairs = []
        if current_layer >= 4:
            disf_counts = count_disfluencies(raw_text)
            if disf_counts.get("total", 0) > 0:
                log(f"Disfluencies: {disf_counts}", "info")
            exposure = compute_exposure_difficulty(raw_text, current_situation, disf_counts, profile)
            if exposure["score"] >= 0.4:
                log(f"Exposure: {exposure['band']} ({exposure['score']}) — triggers used: {exposure['components'].get('trigger_words_used', [])}", "info")
            # Redo detection (anti-compulsion)
            redo_n = check_redo(output)
            if redo_n >= REDO_NUDGE_THRESHOLD:
                log(f"Redo x{redo_n} — consider accepting this version and moving on", "info")
            # Shadow utterance: generate "what you meant to say"
            shadow_result = generate_shadow_utterance(raw_text, profile)
            # Covert avoidance detection (Script Prep vs actual speech)
            covert_pairs = detect_covert_avoidance(raw_text, profile)
            if covert_pairs:
                update_covert_profile(profile, covert_pairs, current_situation)
                for cp in covert_pairs:
                    log(f"Covert avoidance: \"{cp['intended']}\" → \"{cp['said']}\" (avoided /{cp['onset_avoided']}/)", "info")
        # Editorial distance: L2+ (meaningful when any rewrite changes text)
        if current_layer >= 2:
            edit_dist = compute_editorial_distance(raw_text, output)
        # Detect dominant language for this session (majority vote on words)
        _cyr_count = sum(1 for ch in raw_text if '\u0400' <= ch <= '\u04ff')
        _lat_count = sum(1 for ch in raw_text if ch.isalpha() and not ('\u0400' <= ch <= '\u04ff'))
        session_lang = 'ru' if _cyr_count > _lat_count else 'en'
        prosodic_sum = compute_prosodic_summary(prosodic_feats) if prosodic_feats else None
        log_session(profile, raw_text, output, current_tone, current_layer, decision, timings,
                    disf_counts=disf_counts, exposure=exposure, edit_dist=edit_dist,
                    speech_metrics=speech_metrics, lang=session_lang,
                    paralinguistic_events=para_events if para_events else None,
                    prosodic_summary=prosodic_sum)
        state = 'idle'

        # Step 5: Trigger word detection (Layer 4)
        # Capture epoch so background threads can detect if a profile switch occurred
        _epoch_at_launch = _profile_switch_epoch
        if current_layer >= 4:
            regex_triggers = detect_triggers_regex(raw_text)
            if regex_triggers:
                add_trigger_words(regex_triggers, profile)
            def _bg_trigger_detect(rt, out, prof, epoch=_epoch_at_launch):
                if epoch != _profile_switch_epoch:
                    return  # profile switched — discard
                add_trigger_words(detect_triggers_llm(rt, out, prof), prof)
            threading.Thread(target=_bg_trigger_detect, args=(raw_text, output, profile), daemon=True).start()

        # Step 6: Auto-learn (async, Layer 2+)
        # L2 pairs are generic but still reveal corrections/fillers/vocabulary.
        # Learning runs in a background thread — zero latency impact on the pipeline.
        if current_layer >= 2:
            # Track which profile entries were relevant to this session
            track_profile_relevance(profile, raw_text)

            global _learn_counter, _decay_counter
            _learn_counter += 1
            _decay_counter += 1
            learn_status["next_in"] = max(0, LEARN_EVERY - _learn_counter)
            if _learn_counter >= LEARN_EVERY:
                _learn_counter = 0
                learn_status["next_in"] = LEARN_EVERY
                def _bg_learn(prof, epoch=_epoch_at_launch):
                    if epoch != _profile_switch_epoch:
                        return  # profile switched — discard
                    learn_from_sessions(prof)
                threading.Thread(target=_bg_learn, args=(profile,), daemon=True).start()
                # Onset anomaly detection (covert avoidance signal, zero API cost)
                all_sessions = db_get_sessions(limit=200)
                detect_onset_anomalies(all_sessions)

            # Decay sweep: prune stale corrections/fillers/vocab
            if _decay_counter >= DECAY_EVERY:
                _decay_counter = 0
                def _bg_decay(prof, epoch=_epoch_at_launch):
                    if epoch != _profile_switch_epoch:
                        return
                    decay_stale_profile_entries(prof)
                threading.Thread(target=_bg_decay, args=(profile,), daemon=True).start()

        # Step 7: Archive audio for future Whisper fine-tuning
        # Runs synchronously — must complete before finally{} deletes tmp
        if current_layer >= 2 and raw_text and output:
            archive_session_audio(tmp.name, raw_text, output, current_layer, current_situation)

    except Exception as e:
        import traceback
        log(f"Error: {e}\n{traceback.format_exc()}", "error")
        state = 'error'
        threading.Timer(3, lambda: set_state('idle')).start()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def transform_via_command(selected_text, command, tone="casual"):
    """Command Mode: transform selected text per a spoken command via GPT.
    Returns transformed text, or None on failure."""
    try:
        prompt = (
            "You are a text editing assistant. The user has selected text and spoken a "
            "command describing how to transform it. Apply the command to the text and "
            "return ONLY the transformed text — no preamble, no quotes, no explanation. "
            "Preserve the user's meaning and facts. If the command is unclear or the "
            "transformation would change factual content, return the original text."
        )
        user_msg = f"TEXT:\n{selected_text}\n\nCOMMAND: {command}"
        stats_inc("api_calls")
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=1500,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log(f"Command transform failed: {e}", "error")
        return None


_command_prev_clipboard = ""

def start_command_recording():
    """Command Mode: synthesize Ctrl+C to grab selection, then start recording."""
    global is_command_mode, command_selected_text, _command_prev_clipboard
    if is_recording or is_command_mode:
        return
    # Save user's clipboard so we can restore it after the command completes
    _command_prev_clipboard = ""
    try:
        _command_prev_clipboard = pyperclip.paste()
    except Exception:
        pass
    try:
        pyautogui.hotkey('ctrl', 'c')
    except Exception as e:
        log(f"Command Mode: clipboard copy failed: {e}", "error")
        return
    time.sleep(0.15)  # wait for clipboard to populate
    try:
        command_selected_text = pyperclip.paste()
    except Exception:
        command_selected_text = ""
    if not command_selected_text or command_selected_text == _command_prev_clipboard:
        log("Command Mode: no text selected", "warn")
        command_selected_text = ""
        # Restore clipboard even on abort — we may have already copied over it
        try:
            pyperclip.copy(_command_prev_clipboard)
        except Exception:
            pass
        return
    log(f"Command on: \"{command_selected_text[:60]}...\" — speak command", "info")
    is_command_mode = True
    # Start recording (reuses the existing audio pipeline)
    start_recording()


def stop_command_recording():
    """Command Mode: stop recording, transcribe, transform, paste replacement."""
    global is_command_mode, command_selected_text
    if not is_command_mode:
        return
    selected = command_selected_text
    command_selected_text = ""
    is_command_mode = False
    # Stop the audio recording and let the pipeline transcribe it — but we need
    # to intercept the pipeline() output instead of pasting. Simplest approach:
    # run Whisper directly on the buffered audio.
    with lock:
        if not recording:
            stop_recording()
            log("Command Mode: no audio captured", "warn")
            return
        frames = list(recording)
    # Trigger the normal stop (closes audio capture, sets state to processing)
    stop_recording()
    # Run Whisper on the captured audio
    try:
        audio_data = numpy.concatenate(frames, axis=0).flatten()
        if NEEDS_RESAMPLE:
            audio_data = resample_poly(audio_data, RESAMPLE_UP, RESAMPLE_DOWN)
        # Basic preprocessing
        audio_data = audio_data - numpy.mean(audio_data)
        nyq = TARGET_RATE / 2.0
        b_hp, a_hp = butter(2, 70.0 / nyq, btype="highpass")
        audio_data = filtfilt(b_hp, a_hp, audio_data).astype(numpy.float32)
        rms = numpy.sqrt(numpy.mean(audio_data ** 2))
        if rms > 1e-6:
            audio_data = audio_data * (10 ** (-12 / 20) / rms)
        audio_data = numpy.tanh(1.2 * audio_data).astype(numpy.float32)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, audio_data, TARGET_RATE)
        whisper_result, _ = whisper_transcribe(tmp.name)
        os.unlink(tmp.name)
        command_text = whisper_result.get("text", "").strip() if whisper_result else ""
    except Exception as e:
        log(f"Command Mode: transcription failed: {e}", "error")
        set_state('idle')
        return
    if not command_text:
        log("Command Mode: no command heard", "warn")
        set_state('idle')
        return
    log(f"Command: \"{command_text}\"", "info")
    # Transform the selected text per the spoken command
    transformed = transform_via_command(selected, command_text, current_tone)
    if transformed:
        log(f"-> \"{transformed[:80]}...\"", "out")
        paste(transformed)
    else:
        log("Command Mode: transform failed, selection unchanged", "error")
    # Restore user's original clipboard after paste completes
    def _restore_clipboard():
        try:
            pyperclip.copy(_command_prev_clipboard)
        except Exception:
            pass
    threading.Timer(1.5, _restore_clipboard).start()
    set_state('idle')


def paste(text):
    """Copy to clipboard + restore focus + Ctrl+V."""
    global last_paste_time, is_pasting
    now = time.time()
    if now - last_paste_time < 1.0 or is_pasting:
        return
    last_paste_time = now
    is_pasting = True
    try:
        pyperclip.copy(" " + text + " ")
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
        # Layer 4 (Stutter) needs prosodic for severity scaling
        if layer == 4 and not prosodic_enabled:
            set_prosodic(True)
            log("Prosodic auto-enabled for Layer 4 (stutter severity)", "info")

def set_paralinguistic(enabled):
    global paralinguistic_enabled
    paralinguistic_enabled = bool(enabled)
    profile["preferences"]["paralinguistic"] = paralinguistic_enabled
    save_profile(profile)
    log(f"Paralinguistic: {'ON' if paralinguistic_enabled else 'OFF'}", "info")

def set_paralinguistic_transcribe(enabled):
    global paralinguistic_transcribe
    paralinguistic_transcribe = bool(enabled)
    profile["preferences"]["paralinguistic_transcribe"] = paralinguistic_transcribe
    save_profile(profile)
    log(f"Paralinguistic transcribe: {'ON' if paralinguistic_transcribe else 'OFF'}", "info")

def set_prosodic(enabled):
    global prosodic_enabled
    prosodic_enabled = bool(enabled)
    profile["preferences"]["prosodic"] = prosodic_enabled
    save_profile(profile)
    log(f"Prosodic: {'ON' if prosodic_enabled else 'OFF'}", "info")

def set_quiet_mode(enabled):
    global quiet_mode_enabled
    quiet_mode_enabled = bool(enabled)
    profile["preferences"]["quiet_mode"] = quiet_mode_enabled
    save_profile(profile)
    log(f"Quiet Mode: {'ON' if quiet_mode_enabled else 'OFF'}", "info")

def set_mode(mode):
    global current_mode
    if mode in MODES:
        current_mode = mode
        profile["preferences"]["mode"] = current_mode
        save_profile(profile)
        log(f"Mode: {current_mode}", "info")

# Situation pre-warm presets: auto-configure DAF, layer, and prep text
SITUATION_PRESETS = {
    # No auto-prep text — users load their own prep via the Prep tab when they
    # have actual intended text to compare against. Hardcoded template text
    # pollutes covert_profile with false avoidance pairs.
    "high_stress": {"layer": 4, "paralinguistic": True, "prosodic": True},  # DAF removed: user controls DAF manually, preset should not force echo on
    "reading": {"daf_ms": 0, "layer": 3},
}

def set_situation(situation):
    global current_situation, current_layer
    # Resolve aliases from old 6-situation system
    situation = _SITUATION_ALIASES.get(situation, situation)
    if situation in SITUATIONS:
        current_situation = situation
        severity = SITUATION_SEVERITY[situation]
        preset = SITUATION_PRESETS.get(situation, {})
        actions = []
        # Auto-DAF
        if preset.get("daf_ms"):
            daf_start(preset["daf_ms"])
            actions.append(f"DAF:{preset['daf_ms']}ms")
        elif _daf_active and preset.get("daf_ms") == 0:
            # Preset explicitly says "no DAF" (e.g., reading) — turn it off
            daf_stop()
            actions.append("DAF:OFF")
        elif situation == "default" and _daf_active:
            daf_stop()
            actions.append("DAF:OFF")
        # Auto-layer
        if preset.get("layer") and preset["layer"] != current_layer:
            set_layer(preset["layer"])
            actions.append(f"L{preset['layer']}")
        # Auto-toggles
        if "paralinguistic" in preset:
            set_paralinguistic(preset["paralinguistic"])
            if preset["paralinguistic"]:
                actions.append("para:ON")
        if "prosodic" in preset:
            set_prosodic(preset["prosodic"])
            if preset["prosodic"]:
                actions.append("prosodic:ON")
        # Auto-prep text
        if preset.get("prep"):
            set_last_prep(preset["prep"])
            actions.append("prep-loaded")
        # Invalidate clipboard predictor cache — new situation needs fresh scoring
        if _clipboard_predictor:
            _clipboard_predictor.invalidate()
            actions.append("clip-rescan")
        action_str = f" → {', '.join(actions)}" if actions else ""
        log(f"Situation: {situation} (severity: {severity}x){action_str}", "info")

def generate_voice_profile() -> dict:
    """Celebratory Voice Profile — shows what the user accomplished, not what's broken.
    Inverts the clinical framing for non-therapeutic audiences. Zero API cost."""
    from collections import Counter
    sessions = db_get_sessions(limit=1000)
    if not sessions:
        return {"unlocked": False, "words_so_far": 0, "needed": 500}
    total_words = sum(s.get("words", 0) for s in sessions)
    if total_words < 500:
        return {"unlocked": False, "words_so_far": total_words, "needed": 500}

    # ── Catchphrase: most used 2-3 word phrases ─────────────
    phrase_counts = Counter()
    for s in sessions:
        text = (s.get("out") or "").lower()
        words = re.findall(r"\b\w+\b", text)
        for i in range(len(words) - 1):
            phrase_counts[f"{words[i]} {words[i+1]}"] += 1
        for i in range(len(words) - 2):
            phrase_counts[f"{words[i]} {words[i+1]} {words[i+2]}"] += 1
    # Filter out generic/stop-phrase combinations
    _stop = {"of the", "in the", "to the", "on the", "for the", "is a", "it is",
             "this is", "that is", "i am", "i have", "i was", "you are"}
    catchphrase_candidates = [
        (p, c) for p, c in phrase_counts.most_common(50)
        if p not in _stop and c >= 3
    ]
    catchphrase = catchphrase_candidates[0] if catchphrase_candidates else None

    # ── Peak dictation time: what hour had most sessions ────
    hour_counts = Counter()
    dow_counts = Counter()
    for s in sessions:
        try:
            dt = datetime.fromisoformat(s.get("ts", ""))
            hour_counts[dt.hour] += 1
            dow_counts[dt.strftime("%A")] += 1
        except Exception:
            pass
    peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else None
    peak_day = dow_counts.most_common(1)[0][0] if dow_counts else None

    # ── Dictation superpower: inferred from behavior ───────
    layer_counts = Counter(s.get("layer", 1) for s in sessions)
    tone_counts = Counter(s.get("tone", "casual") for s in sessions)
    avg_words_per_session = total_words / len(sessions) if sessions else 0
    fav_tone = tone_counts.most_common(1)[0][0] if tone_counts else "casual"
    fav_layer = layer_counts.most_common(1)[0][0] if layer_counts else 1

    if avg_words_per_session >= 30:
        superpower = "Long-form dictator"
    elif fav_tone == "formal":
        superpower = "Formal communicator"
    elif fav_tone == "professional":
        superpower = "Business operator"
    elif fav_layer >= 4:
        superpower = "Clinical precision"
    elif len(sessions) >= 100:
        superpower = "Daily habit"
    else:
        superpower = "Rapid drafter"

    # ── Headline: one-line celebration ─────────────────────
    headlines = [
        f"You dictated {total_words:,} words — that's an email you didn't have to type.",
        f"You've had {len(sessions)} conversations with your keyboard without typing.",
        f"That's {total_words:,} words you said out loud instead of typing.",
    ]
    headline = headlines[total_words % len(headlines)]

    # ── Streak: consecutive days with at least one session ─
    day_set = set()
    for s in sessions:
        try:
            day_set.add(datetime.fromisoformat(s.get("ts", "")).date())
        except Exception:
            pass
    streak = 0
    today = datetime.now().date()
    check = today
    while check in day_set:
        streak += 1
        check = check - timedelta(days=1)

    return {
        "unlocked": True,
        "headline": headline,
        "total_words": total_words,
        "total_sessions": len(sessions),
        "avg_words_per_session": round(avg_words_per_session, 1),
        "catchphrase": {"phrase": catchphrase[0], "count": catchphrase[1]} if catchphrase else None,
        "peak_hour": peak_hour,
        "peak_day": peak_day,
        "superpower": superpower,
        "favorite_tone": fav_tone,
        "favorite_layer": fav_layer,
        "streak_days": streak,
    }


def generate_clinical_profile(min_sessions: int = 20) -> dict:
    """Generate a longitudinal disfluency profile from accumulated session data.

    Returns a structured dict suitable for display, PDF export, or API response.
    Requires min_sessions before generating (default 20).
    """
    sessions = db_get_sessions(limit=500)

    if len(sessions) < min_sessions:
        return {"error": f"Need {min_sessions} sessions, have {len(sessions)}"}

    # Sort oldest-first for trend computation
    sessions_asc = list(reversed(sessions))
    first_ts = sessions_asc[0].get("ts", "")
    last_ts = sessions_asc[-1].get("ts", "")

    # Total duration in minutes (words / avg wpm; fallback estimate)
    total_words = sum(s.get("words", 0) for s in sessions)
    total_minutes = round(total_words / 130, 1) if total_words else 0

    # --- Primary disfluency type ---
    type_counts: dict = {}
    for s in sessions:
        dc = s.get("disfluency_counts", {})
        if isinstance(dc, dict):
            for k, v in dc.items():
                if k != "total":
                    type_counts[k] = type_counts.get(k, 0) + (v or 0)
    total_disf_events = sum(type_counts.values())
    primary_type = max(type_counts, key=type_counts.get) if type_counts else "unknown"
    primary_pct = round(type_counts[primary_type] / total_disf_events * 100) if total_disf_events else 0

    # --- Frequency per minute ---
    freq_per_min = round(total_disf_events / total_minutes, 1) if total_minutes else 0

    # --- Frequency trend (first quartile vs last quartile) ---
    q = max(len(sessions_asc) // 4, 1)
    first_q = sessions_asc[:q]
    last_q = sessions_asc[-q:]
    def _disf_rate(sess_list):
        events = sum(sum(v for k, v in (s.get("disfluency_counts") or {}).items() if k != "total") for s in sess_list)
        words = sum(s.get("words", 0) for s in sess_list)
        return (events / (words / 130)) if words else 0
    first_rate = _disf_rate(first_q)
    last_rate = _disf_rate(last_q)
    freq_trend = round((last_rate - first_rate) / first_rate * 100) if first_rate else 0

    # --- Situational breakdown ---
    sit_data: dict = {}
    for s in sessions:
        sit = s.get("situation", "default")
        dc = s.get("disfluency_counts", {}) or {}
        events = sum(v for k, v in dc.items() if k != "total")
        w = s.get("words", 0)
        rate = (events / (w / 130)) if w else 0
        if sit not in sit_data:
            sit_data[sit] = {"rates": []}
        sit_data[sit]["rates"].append(rate)
    baseline_rate = (sum(sit_data.get("default", {}).get("rates", [0])) /
                     max(len(sit_data.get("default", {}).get("rates", [1])), 1))
    situational_breakdown = {}
    for sit, d in sit_data.items():
        avg = round(sum(d["rates"]) / max(len(d["rates"]), 1), 1)
        entry: dict = {"rate": avg}
        if sit == "default":
            entry["label"] = "baseline"
        elif baseline_rate:
            pct = round((avg - baseline_rate) / baseline_rate * 100)
            entry["vs_baseline"] = f"{'+' if pct >= 0 else ''}{pct}%"
        situational_breakdown[sit] = entry

    # --- Onset triggers ---
    onset_weights = profile.get("onset_weights", {})
    top_onset_triggers = []
    for onset, weight in sorted(onset_weights.items(), key=lambda x: -x[1])[:5]:
        if weight >= 0.3:
            # Count trigger words using this onset
            events = sum(
                v for s in sessions
                for k, v in (s.get("disfluency_counts") or {}).items()
                if k != "total"
            ) // max(len(onset_weights), 1)
            top_onset_triggers.append({
                "onset": f"/{onset}/",
                "weight": round(weight, 2),
                "events": events,
            })

    # --- Covert avoidance ---
    covert = profile.get("covert_profile", {}).get("avoidance_pairs", {})
    active_pairs = 0
    avoided_total = 0
    used_total = 0
    for sit_words in covert.values():
        for word, data in sit_words.items():
            active_pairs += 1
            avoided_total += data.get("avoided_count", 0)
            used_total += data.get("used_count", avoided_total)
    avoidance_rate = round(avoided_total / (avoided_total + used_total) * 100) if (avoided_total + used_total) else 0

    # --- Fluency trend (editorial distance, lower = better) ---
    edit_dists = [s["editorial_distance"] for s in sessions_asc if s.get("editorial_distance") is not None]
    fluency_scores = [round(1.0 - min(ed, 1.0), 2) for ed in edit_dists]
    improvement = 0
    if len(fluency_scores) >= 4:
        fq = max(len(fluency_scores) // 4, 1)
        first_f = sum(fluency_scores[:fq]) / fq
        last_f = sum(fluency_scores[-fq:]) / fq
        improvement = round((last_f - first_f) / first_f * 100) if first_f else 0
    avg_edit = round(sum(edit_dists) / len(edit_dists), 2) if edit_dists else None

    # --- Exposure ---
    exposure_scores = []
    exposure_bands: list = []
    for s in sessions:
        exp = s.get("exposure", {})
        if exp and "score" in exp:
            exposure_scores.append(exp["score"])
            exposure_bands.append(exp.get("band", "low"))
    avg_exposure = round(sum(exposure_scores) / len(exposure_scores), 2) if exposure_scores else None
    avg_band = max(set(exposure_bands), key=exposure_bands.count) if exposure_bands else "unknown"
    high_diff_pct = round(exposure_bands.count("very_high") / len(exposure_bands) * 100) if exposure_bands else 0

    return {
        "user": profile.get("name", "Unknown"),
        "period": {"start": first_ts, "end": last_ts},
        "total_sessions": len(sessions),
        "total_minutes": total_minutes,
        "primary_disfluency": {
            "type": primary_type,
            "percentage": primary_pct,
        },
        "frequency_per_minute": freq_per_min,
        "frequency_trend": freq_trend,
        "situational_breakdown": situational_breakdown,
        "top_onset_triggers": top_onset_triggers,
        "covert_avoidance": {
            "active_pairs": active_pairs,
            "avoidance_rate": avoidance_rate,
            "trend": "decreasing" if avoidance_rate < 40 else "stable",
        },
        "fluency_trend": {
            "scores": fluency_scores[-20:],
            "improvement": improvement,
        },
        "editorial_distance": {
            "average": avg_edit,
            "trend": "decreasing" if (avg_edit is not None and avg_edit < 0.35) else "stable",
        },
        "exposure": {
            "average_band": avg_band,
            "average_score": avg_exposure,
            "high_difficulty_sessions_pct": high_diff_pct,
        },
    }


# -- Dashboard HTTP server ────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        origin = self.headers.get('Origin', '')
        if origin in ('http://127.0.0.1:7878', 'http://localhost:7878', 'null'):
            self.send_header('Access-Control-Allow-Origin', origin)
        else:
            self.send_header('Access-Control-Allow-Origin', 'null')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _compute_avg_edit_dist(self):
        """Average editorial distance from recent sessions."""
        sessions = db_get_sessions(limit=20)
        dists = [s["editorial_distance"] for s in sessions
                 if s.get("editorial_distance") is not None]
        return round(sum(dists) / len(dists), 3) if dists else 0.0

    def _compute_avg_exposure(self):
        """Average exposure difficulty score from recent sessions."""
        sessions = db_get_sessions(limit=20)
        scores = [s["exposure"]["score"] for s in sessions
                  if s.get("exposure") and isinstance(s["exposure"], dict) and "score" in s["exposure"]]
        if not scores:
            return {"score": 0.0, "band": "no_data"}
        avg = sum(scores) / len(scores)
        band = ("very_high" if avg >= 0.7 else "high" if avg >= 0.5 else
                "moderate" if avg >= 0.3 else "low")
        return {"score": round(avg, 2), "band": band}

    def do_GET(self):
        if self.path == '/':
            dash = Path(__file__).parent / 'dashboard.html'
            self._serve_file(dash, 'text/html')
        elif self.path == '/mobile':
            mobile_path = Path(__file__).parent / 'mobile.html'
            self._serve_file(mobile_path, 'text/html')
        elif self.path == '/manifest.json':
            manifest_path = Path(__file__).parent / 'manifest.json'
            self._serve_file(manifest_path, 'application/json')
        elif self.path == '/sw.js':
            sw_path = Path(__file__).parent / 'sw.js'
            self._serve_file(sw_path, 'application/javascript')
        elif self.path == '/onboard':
            self._serve_file(Path(__file__).parent / 'onboard.html', 'text/html')
        elif self.path == '/auth/google':
            self._serve_file(Path(__file__).parent / 'auth_google.html', 'text/html')
        elif self.path == '/api/state':
            # Network status: green if recent API success, red if recent error, gray if idle
            _now = time.time()
            if _last_api_error_ts > _last_api_ok_ts and _now - _last_api_error_ts < 60:
                _net_status = "error"
            elif _last_api_ok_ts > 0 and _now - _last_api_ok_ts < 300:
                _net_status = "ok"
            else:
                _net_status = "idle"
            self._json({
                'state': ('command' if is_command_mode else state),
                'is_command_mode': is_command_mode,
                'network_status': _net_status,
                'network_error': _last_api_error_msg if _net_status == "error" else "",
                'tone': current_tone,
                'layer': current_layer,
                'layer_name': LAYER_NAMES.get(current_layer, '?'),
                'situation': current_situation,
                'situation_severity': SITUATION_SEVERITY.get(current_situation, 1.0),
                'stats': stats,
                'model': MODEL_L4 if current_layer >= 4 else MODEL,
                'whisper_temp': WHISPER_TEMP,
                'whisper_no_speech_threshold': WHISPER_NO_SPEECH_THRESHOLD,
                'whisper_multi_temp': WHISPER_MULTI_TEMP,
                'speech_metrics': _last_speech_metrics,
                'avg_logprob': _last_avg_logprob,
                'redo_count': _redo_count,
                'block_count': _block_count,
                'avg_exposure': self._compute_avg_exposure(),
                'paralinguistic_events': _last_paralinguistic_events,
                'speaker_state': _last_speaker_state,
                'paralinguistic_enabled': paralinguistic_enabled,
                'paralinguistic_transcribe': paralinguistic_transcribe,
                'prosodic_enabled': prosodic_enabled,
                'quiet_mode_enabled': quiet_mode_enabled,
                'profile_name': _active_profile_name,
                'auth': {
                    'signed_in': is_authenticated(),
                    'user': _auth_user,
                    'has_local_key': bool(API_KEY),
                },
            })
        elif self.path == '/api/profiles':
            self._json({
                'profiles': list_profiles(),
                'active': _active_profile_name,
            })
        elif self.path == '/api/profile':
            self._json(profile)
        elif self.path == '/api/sessions':
            self._json(db_get_sessions(limit=50))
        elif self.path == '/api/log':
            self._json(console_log)
        elif self.path == '/api/learn':
            # Compute fluency improvement from editorial distance trend
            _fl_sessions = db_get_sessions(limit=50)
            _fl_dists = [s["editorial_distance"] for s in _fl_sessions
                         if s.get("editorial_distance") is not None]
            _fl_imp = None
            if len(_fl_dists) >= 6:
                half = len(_fl_dists) // 2
                first_avg = sum(_fl_dists[:half]) / half
                second_avg = sum(_fl_dists[half:]) / half
                if first_avg > 0:
                    _fl_imp = round((first_avg - second_avg) / first_avg * 100, 1)
            learn_status_with_fluency = dict(learn_status)
            learn_status_with_fluency['fluency_improvement'] = _fl_imp
            self._json({
                'status': learn_status_with_fluency,
                'events': _learn_events_snapshot(),
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
                },
                'avg_edit_dist': self._compute_avg_edit_dist(),
                'redo_count': _redo_count,
                'low_conf_segments': _last_low_conf_segments[:10],
                'avg_logprob': _last_avg_logprob,
                'insights': build_stutter_insights(profile) if current_layer >= 4 else [],
                'insights_enabled': current_layer >= 4,
                'onset_weights': {
                    'personal': _personal_onset_weights,
                    'by_lang': _personal_onset_weights_by_lang,
                    'dominant': _personal_dominant_onsets,
                    'has_data': bool(_personal_onset_weights),
                },
                'trigger_types': profile.get('trigger_types', {}),
                'severity': compute_severity_score(),
                'covert_profile': profile.get('covert_profile', {}),
                'onset_anomalies': _onset_anomalies,
                'substitution_fingerprint': compute_substitution_fingerprint(profile),
                'shadow_utterance': {
                    'history': list(_shadow_history[-5:]),
                    'trend': compute_avoidance_trend(),
                },
                'decay': {
                    'stale_threshold': DECAY_STALE_SESSIONS,
                    'dead_threshold': DECAY_DEAD_SESSIONS,
                    'sweep_every': DECAY_EVERY,
                    'next_sweep_in': max(0, DECAY_EVERY - _decay_counter),
                    'relevance_tracked': bool(profile.get('_relevance')),
                },
            })
        elif self.path == '/api/wer':
            # Compute WER stats from recent sessions (raw vs corrected)
            sessions = db_get_sessions(limit=100)
            l2_plus = [s for s in sessions if s.get("layer", 1) >= 2 and s.get("raw") != s.get("out")]
            if l2_plus:
                wers = []
                for s in l2_plus:
                    w, _, _, _ = compute_wer(s["out"], s["raw"])
                    wers.append(w)
                avg_wer = sum(wers) / len(wers)
                recent_wers = wers[:10]
                recent_avg = sum(recent_wers) / len(recent_wers) if recent_wers else 0
                self._json({
                    'avg_wer': round(avg_wer, 4),
                    'recent_wer': round(recent_avg, 4),
                    'sample_count': len(l2_plus),
                    'interpretation': (
                        'excellent (<10%)' if avg_wer < 0.10 else
                        'good (10-20%)' if avg_wer < 0.20 else
                        'moderate (20-30%) — reconstruction doing heavy lifting' if avg_wer < 0.30 else
                        'high (>30%) — fine-tuned local Whisper would help significantly'
                    )
                })
            else:
                self._json({'avg_wer': None, 'sample_count': 0, 'interpretation': 'no data yet'})
        elif self.path == '/api/fluency':
            # Historical fluency metrics from persisted speech_metrics per session
            sessions = db_get_sessions(limit=50)
            trend = []
            lang_dist = {"en": 0, "ru": 0}
            for s in sessions:
                sm = s.get("speech_metrics")
                if sm and sm.get("pause_ratio") is not None:
                    trend.append({
                        "ts": s["ts"][:16],
                        "pause_ratio": sm["pause_ratio"],
                        "speaking_rate": sm.get("speaking_rate_sps", 0),
                        "severity_modifier": sm.get("severity_modifier", 0),
                        "situation": s.get("situation", "default"),
                        "lang": s.get("lang", "en"),
                    })
                lang_dist[s.get("lang", "en")] = lang_dist.get(s.get("lang", "en"), 0) + 1
            # Compute averages
            if trend:
                avg_pause = round(sum(t["pause_ratio"] for t in trend) / len(trend), 3)
                avg_rate = round(sum(t["speaking_rate"] for t in trend) / len(trend), 2)
                avg_sev = round(sum(t["severity_modifier"] for t in trend) / len(trend), 2)
                # Trend direction: compare last 5 vs previous 5
                recent_5 = [t["pause_ratio"] for t in trend[:5]]
                prev_5 = [t["pause_ratio"] for t in trend[5:10]]
                if recent_5 and prev_5:
                    r_avg = sum(recent_5) / len(recent_5)
                    p_avg = sum(prev_5) / len(prev_5)
                    pause_trend = "improving" if r_avg < p_avg - 0.03 else \
                                  "worsening" if r_avg > p_avg + 0.03 else "stable"
                else:
                    pause_trend = "insufficient_data"
            else:
                avg_pause = avg_rate = avg_sev = 0
                pause_trend = "no_data"
            # Severity breakdown (current session)
            base_sev = SITUATION_SEVERITY.get(current_situation, 1.0)
            sev_mod = _last_speech_metrics.get("severity_modifier", 0) if _last_speech_metrics else 0
            self._json({
                "trend": trend,  # newest first
                "avg_pause_ratio": avg_pause,
                "avg_speaking_rate": avg_rate,
                "avg_severity_modifier": avg_sev,
                "pause_trend": pause_trend,
                "sample_count": len(trend),
                "lang_distribution": lang_dist,
                "severity_breakdown": {
                    "base": base_sev,
                    "situation": current_situation,
                    "speech_modifier": sev_mod,
                    "final": round(base_sev + sev_mod, 2),
                    "aggression": (
                        "HIGH" if base_sev + sev_mod >= 1.6 else
                        "MODERATE" if base_sev + sev_mod >= 1.2 else
                        "LOW"
                    ),
                },
                "current": _last_speech_metrics or {},
            })
        elif self.path == '/api/archive':
            # Archive stats
            count = 0
            total_bytes = 0
            if ARCHIVE_DIR.exists():
                wavs = list(ARCHIVE_DIR.glob("*.wav"))
                count = len(wavs)
                total_bytes = sum(f.stat().st_size for f in ARCHIVE_DIR.rglob("*") if f.is_file())
            self._json({
                'enabled': ARCHIVE_AUDIO,
                'sessions_archived': count,
                'size_mb': round(total_bytes / (1024 * 1024), 1),
                'max_mb': ARCHIVE_MAX_MB,
                'path': str(ARCHIVE_DIR),
                'ready_for_finetuning': count >= 50,
                'finetuning_note': (
                    f'{count} sessions archived — need ~50 for meaningful fine-tuning'
                    if count < 50 else
                    f'{count} sessions archived — sufficient for LoRA fine-tuning'
                )
            })
        elif self.path == '/api/report':
            # Weekly clinical report — GPT summarizes recent session data
            sessions = db_get_sessions(limit=100)
            if not sessions:
                self._json({"report": "No sessions recorded yet.", "data": {}})
            else:
                # Extract report data
                edit_dists = [s["editorial_distance"] for s in sessions if s.get("editorial_distance") is not None]
                sit_breakdown = {}
                lang_breakdown = {"en": 0, "ru": 0}
                total_words = 0
                total_redos = 0
                onset_triggers = {}
                for s in sessions:
                    sit = s.get("situation", "default")
                    sit_breakdown[sit] = sit_breakdown.get(sit, 0) + 1
                    total_words += s.get("words", 0)
                    lang_breakdown[s.get("lang", "en")] = lang_breakdown.get(s.get("lang", "en"), 0) + 1
                    sm = s.get("speech_metrics")
                    if sm:
                        total_redos += 1 if sm.get("severity_modifier", 0) > 0.2 else 0
                triggers = profile.get("trigger_words", [])
                for t in triggers[:20]:
                    onset = _extract_onset(t)
                    if onset:
                        onset_triggers[onset] = onset_triggers.get(onset, 0) + 1
                # Compute pause data from sessions with speech_metrics
                pause_data = [s["speech_metrics"]["pause_ratio"] for s in sessions
                              if s.get("speech_metrics") and s["speech_metrics"].get("pause_ratio") is not None]
                report_data = {
                    "total_sessions": len(sessions),
                    "total_words": total_words,
                    "avg_edit_dist": round(sum(edit_dists) / len(edit_dists), 3) if edit_dists else None,
                    "edit_dist_trend": {
                        "first_half": round(sum(edit_dists[len(edit_dists)//2:]) / max(len(edit_dists)//2, 1), 3) if edit_dists else None,
                        "second_half": round(sum(edit_dists[:len(edit_dists)//2]) / max(len(edit_dists)//2, 1), 3) if edit_dists else None,
                    },
                    "situation_breakdown": sit_breakdown,
                    "language_breakdown": lang_breakdown,
                    "avg_pause_ratio": round(sum(pause_data) / len(pause_data), 3) if pause_data else None,
                    "top_onset_triggers": dict(sorted(onset_triggers.items(), key=lambda x: -x[1])[:5]),
                    "trigger_count": len(triggers),
                    "corrections_count": len(profile.get("corrections", {})),
                    "covert_avoidance_events": sum(
                        entry.get("avoided_count", 0)
                        for sit_words in profile.get("covert_profile", {}).get("avoidance_pairs", {}).values()
                        for entry in sit_words.values()
                    ),
                }
                stats_inc("api_calls")
                try:
                    resp = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "system", "content": (
                            "You are a speech-language pathology assistant generating a clinical weekly "
                            "progress report for a person who stutters. Be direct, use data. Use emoji "
                            "sparingly (✅ ❌ 🎯 📞). Format as a concise summary with bullet points. "
                            "Highlight improvements, flag concerns, suggest focus areas."
                        )}, {"role": "user", "content": (
                            f"Generate a weekly clinical stutter progress report from this data:\n"
                            f"{json.dumps(report_data, indent=2)}"
                        )}],
                        max_tokens=600, temperature=0.3
                    )
                    self._json({
                        "report": resp.choices[0].message.content.strip(),
                        "data": report_data
                    })
                except Exception as e:
                    log(f"Report generation failed: {e}", "error")
                    self._json({"report": f"Report generation failed: {e}", "data": report_data})
        elif self.path == '/api/preview':
            with preview_lock:
                text = preview_state['text']
                # Score each word for phonetic risk (live trigger warning)
                scored_words = []
                if text:
                    words = text.split()
                    n = len(words)
                    trigger_set = {t.lower() for t in profile.get('trigger_words', [])}
                    for i, w in enumerate(words):
                        risk = predict_phonetic_risk(w, sentence_position=i, sentence_length=n)
                        if w.lower() in trigger_set:
                            risk = 1.0
                        scored_words.append({"word": w, "risk": round(risk, 2)})
                self._json({
                    'enabled': LIVE_PREVIEW_ENABLED,
                    'active': preview_state['active'],
                    'text': text,
                    'scored_words': scored_words,
                    'final_text': preview_state['final_text'],
                    'updated_at': preview_state['updated_at']
                })
        elif self.path == '/api/daf':
            self._json({
                'active': _daf_active,
                'delay_ms': _daf_delay_ms,
                'min': DAF_MIN_DELAY_MS,
                'max': DAF_MAX_DELAY_MS
            })
        elif self.path == '/api/calibration':
            status = calibration_status()
            nxt = calibration_next_prompt()
            status["next_prompt"] = nxt
            self._json(status)
        elif self.path == '/api/calibration/prompts':
            self._json(CALIBRATION_PROMPTS)
        elif self.path == '/api/augment':
            self._json(augment_status())
        elif self.path == '/api/severity':
            self._json(compute_severity_score())
        elif self.path == '/api/hotkeys':
            self._json({
                'record': RECORD_KEY.upper(),
                'tone': TONE_KEY.upper(),
                'layer': LAYER_KEY.upper(),
                'stats': STATS_KEY.upper(),
                'quit': QUIT_KEY.upper(),
            })
        elif self.path == '/api/patience':
            self._json({"patience": get_patience_timeout(),
                        "default": PATIENCE_DEFAULT,
                        "stutter": PATIENCE_STUTTER})
        elif self.path == '/api/clinical_profile':
            profile_data = generate_clinical_profile()
            self._json(profile_data)
        elif self.path == '/api/voice_profile':
            self._json(generate_voice_profile())
        else:
            self.send_error(404)

    def do_POST(self):
        body = self._read_body()
        if self.path == '/api/auth':
            global _firebase_id_token, _auth_user
            _action_str = (body or {}).get('action', 'NONE') if body else 'NO_BODY'
            _has_token = bool((body or {}).get('id_token')) if body else False
            log(f"[AUTH] /api/auth received: action={_action_str} has_token={_has_token}", "info")
            if body and body.get('action') == 'sign_in' and body.get('id_token'):
                _firebase_id_token = body['id_token']
                _auth_user = {
                    'email': body.get('email', ''),
                    'displayName': body.get('displayName', ''),
                    'uid': body.get('uid', ''),
                }
                log(f"Google Sign-In: {_auth_user.get('email', 'unknown')}", "info")
                # Auto-switch to a profile linked to this Google account
                email = body.get('email', '').strip()
                if email:
                    profile_name = email.split('@')[0]  # "george" from "george@gmail.com"
                    try:
                        log(f"[AUTH] step1: checking if profile '{profile_name}' exists", "info")
                        existing = list_profiles()
                        log(f"[AUTH] step2: existing profiles = {existing}", "info")
                        if profile_name not in existing:
                            log(f"[AUTH] step3: creating profile '{profile_name}'", "info")
                            create_profile(profile_name)
                            log(f"[AUTH] step4: created profile for {email}: {profile_name}", "info")
                        log(f"[AUTH] step5: about to switch_profile('{profile_name}')", "info")
                        switch_profile(profile_name)
                        log(f"[AUTH] step6: switch_profile returned successfully", "info")
                    except Exception as e:
                        import traceback
                        log(f"[AUTH] Profile switch FAILED: {type(e).__name__}: {e}", "error")
                        log(f"[AUTH] Traceback: {traceback.format_exc()[:600]}", "error")
                self._json({'signed_in': True, 'user': _auth_user, 'profile': _active_profile_name})
            elif body and body.get('action') == 'sign_out':
                _firebase_id_token = None
                _auth_user = None
                log("Google Sign-Out", "info")
                # Switch back to Default profile
                try:
                    switch_profile("Default")
                except Exception as e:
                    log(f"Profile switch on sign-out failed: {e}", "error")
                self._json({'signed_in': False, 'profile': _active_profile_name})
            elif body and body.get('action') == 'refresh' and body.get('id_token'):
                _firebase_id_token = body['id_token']
                self._json({'signed_in': True, 'refreshed': True})
            else:
                self._json({'signed_in': is_authenticated(), 'user': _auth_user})
        elif self.path == '/api/open-signin':
            # Open Google sign-in in the system default browser.
            # Edge --app= mode + pywebview both register as embedded browsers and
            # Google refuses OAuth there. Popping the real system browser lets
            # OAuth complete normally; auth_google.html posts the token back to /api/auth.
            import webbrowser
            try:
                opened = webbrowser.open('http://localhost:7878/auth/google', new=2)
                log(f"[AUTH] /api/open-signin called — webbrowser.open returned {opened}", "info")
                self._json({'ok': True, 'browser_opened': bool(opened)})
            except Exception as e:
                log(f"[AUTH] /api/open-signin EXCEPTION: {e}", "error")
                self._json({'ok': False, 'error': str(e)[:200]})
        elif self.path == '/api/tone':
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
        elif self.path == '/api/paralinguistic':
            if body and 'enabled' in body:
                set_paralinguistic(body['enabled'])
            self._json({'paralinguistic_enabled': paralinguistic_enabled})
        elif self.path == '/api/paralinguistic_transcribe':
            if body and 'enabled' in body:
                set_paralinguistic_transcribe(body['enabled'])
            self._json({'paralinguistic_transcribe': paralinguistic_transcribe})
        elif self.path == '/api/prosodic':
            if body and 'enabled' in body:
                set_prosodic(body['enabled'])
            self._json({'prosodic_enabled': prosodic_enabled})
        elif self.path == '/api/quiet_mode':
            if body and 'enabled' in body:
                set_quiet_mode(body['enabled'])
            self._json({'quiet_mode_enabled': quiet_mode_enabled})
        elif self.path == '/api/mode':
            if body and isinstance(body.get('mode'), str):
                set_mode(body['mode'].upper())
            self._json({'mode': current_mode})
        elif self.path == '/api/situation':
            if body and isinstance(body.get('situation'), str):
                set_situation(body['situation'].lower())
            preset = SITUATION_PRESETS.get(current_situation, {})
            self._json({
                'situation': current_situation,
                'severity': SITUATION_SEVERITY.get(current_situation, 1.0),
                'situations': SITUATIONS,
                'preset_applied': {
                    'daf_ms': preset.get('daf_ms', 0),
                    'layer': preset.get('layer'),
                    'prep_loaded': bool(preset.get('prep')),
                } if preset else None,
            })
        elif self.path == '/api/profiles/switch':
            if body and isinstance(body.get('name'), str):
                try:
                    switched = switch_profile(body['name'])
                    self._json({'ok': True, 'active': switched, 'profiles': list_profiles()})
                except ValueError as e:
                    self._json({'ok': False, 'error': str(e)})
            else:
                self._json({'ok': False, 'error': 'Missing name'})
        elif self.path == '/api/profiles/create':
            if body and isinstance(body.get('name'), str):
                try:
                    created = create_profile(body['name'])
                    self._json({'ok': True, 'name': created, 'profiles': list_profiles()})
                except ValueError as e:
                    self._json({'ok': False, 'error': str(e)})
            else:
                self._json({'ok': False, 'error': 'Missing name'})
        elif self.path == '/api/reset_timer':
            stats["start_time"] = time.time()
            log("Timer reset", "info")
            self._json({'start_time': stats["start_time"]})
        elif self.path == '/api/profile':
            if body and isinstance(body, dict):
                for key in ('trigger_words', 'filler_words', 'vocabulary'):
                    if key in body and isinstance(body[key], list):
                        profile[key] = _dedupe_list(
                            [str(v) for v in body[key] if isinstance(v, str)])
                if 'corrections' in body and isinstance(body['corrections'], dict):
                    profile['corrections'] = _norm_corrections({
                        str(k): str(v) for k, v in body['corrections'].items()
                        if isinstance(k, str) and isinstance(v, str)
                    })
                save_profile(profile)
            self._json({'ok': True})
        elif self.path == '/api/daf':
            if body and isinstance(body, dict):
                if 'active' in body:
                    if body['active']:
                        daf_start(body.get('delay_ms'))
                    else:
                        daf_stop()
                elif 'delay_ms' in body:
                    try:
                        daf_set_delay(int(body['delay_ms']))
                    except (ValueError, TypeError):
                        pass
            self._json({
                'active': _daf_active,
                'delay_ms': _daf_delay_ms
            })
        elif self.path == '/api/whisper_temp':
            global WHISPER_TEMP
            if body and 'temperature' in body:
                try:
                    t = float(body['temperature'])
                    WHISPER_TEMP = max(0.0, min(1.0, t))
                    log(f"Whisper temperature: {WHISPER_TEMP}", "info")
                except (ValueError, TypeError):
                    pass
            self._json({'temperature': WHISPER_TEMP})
        elif self.path == '/api/whisper_config':
            global WHISPER_NO_SPEECH_THRESHOLD, WHISPER_MULTI_TEMP
            if body:
                if 'no_speech_threshold' in body:
                    try:
                        v = float(body['no_speech_threshold'])
                        WHISPER_NO_SPEECH_THRESHOLD = max(0.0, min(1.0, v))
                        log(f"Whisper no_speech_threshold: {WHISPER_NO_SPEECH_THRESHOLD}", "info")
                    except (ValueError, TypeError):
                        pass
                if 'multi_temp' in body:
                    WHISPER_MULTI_TEMP = bool(body['multi_temp'])
                    log(f"Whisper multi-temp voting: {'ON' if WHISPER_MULTI_TEMP else 'OFF'}", "info")
            self._json({
                'temperature': WHISPER_TEMP,
                'no_speech_threshold': WHISPER_NO_SPEECH_THRESHOLD,
                'multi_temp': WHISPER_MULTI_TEMP,
                'multi_temps': WHISPER_MULTI_TEMPS,
            })
        elif self.path == '/api/prep':
            if body and isinstance(body.get('text'), str):
                result = prep_text(body['text'], profile)
                self._json(result)
            else:
                self._json({"error": "Send {\"text\": \"your script here\"}"})
        elif self.path == '/api/covert/remove':
            # Remove a specific avoidance pair from covert_profile
            if body and 'situation' in body and 'word' in body:
                sit = body['situation']
                word = body['word']
                pairs = profile.get('covert_profile', {}).get('avoidance_pairs', {})
                if sit in pairs:
                    if word in pairs[sit]:
                        del pairs[sit][word]
                        save_profile(profile)
                        log(f"Removed covert pair: {word} from {sit}", "info")
                        self._json({"removed": True, "word": word, "situation": sit})
                    else:
                        self._json({"removed": False, "error": "word not found"})
                else:
                    self._json({"removed": False, "error": "situation not found"})
            else:
                self._json({"error": "Send {\"situation\": \"...\", \"word\": \"...\"}"})
        elif self.path == '/api/calibration/start':
            _calibration_state["active"] = True
            _calibration_state["started_at"] = datetime.now().isoformat()
            log("Calibration mode started", "info")
            nxt = calibration_next_prompt()
            self._json({"started": True, "next_prompt": nxt, "status": calibration_status()})
        elif self.path == '/api/calibration/stop':
            _calibration_state["active"] = False
            log(f"Calibration stopped — {len(_calibration_state['completed'])}/{len(CALIBRATION_PROMPTS)} completed", "info")
            self._json({"stopped": True, "status": calibration_status()})
        elif self.path == '/api/calibration/record':
            # Receives base64-encoded WAV audio for a specific prompt
            if body and 'prompt_id' in body and 'audio_b64' in body:
                import base64
                tmp = None
                try:
                    audio_bytes = base64.b64decode(body['audio_b64'])
                    # Write to temp file, read back as numpy array
                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp.write(audio_bytes)
                    tmp.close()
                    audio_data, sr = sf.read(tmp.name)
                    result = calibration_save_audio(int(body['prompt_id']), audio_data, sr)
                    result["next_prompt"] = calibration_next_prompt()
                    result["status"] = calibration_status()
                    self._json(result)
                except Exception as e:
                    log(f"Calibration record failed: {e}", "error")
                    self._json({"error": str(e)})
                finally:
                    if tmp:
                        try: os.unlink(tmp.name)
                        except OSError: pass
            else:
                self._json({"error": "Send {\"prompt_id\": N, \"audio_b64\": \"...\"}"})
        elif self.path == '/api/calibration/skip':
            if body and 'prompt_id' in body:
                pid = int(body['prompt_id'])
                if pid not in _calibration_state["skipped"]:
                    _calibration_state["skipped"].append(pid)
                self._json({"skipped": pid, "next_prompt": calibration_next_prompt(), "status": calibration_status()})
            else:
                self._json({"error": "Send {\"prompt_id\": N}"})
        elif self.path == '/api/hotkeys':
            global RECORD_KEY, TONE_KEY, LAYER_KEY, STATS_KEY, QUIT_KEY
            if body and isinstance(body, dict):
                valid_keys = {'f1','f2','f3','f4','f5','f6','f7','f8','f9','f10','f11','f12'}
                if 'record' in body:
                    k = str(body['record']).lower()
                    if k in valid_keys:
                        RECORD_KEY = k
                if 'tone' in body:
                    k = str(body['tone']).lower()
                    if k in valid_keys:
                        TONE_KEY = k
                if 'layer' in body:
                    k = str(body['layer']).lower()
                    if k in valid_keys:
                        LAYER_KEY = k
                if 'stats' in body:
                    k = str(body['stats']).lower()
                    if k in valid_keys:
                        STATS_KEY = k
                if 'quit' in body:
                    k = str(body['quit']).lower()
                    if k in valid_keys:
                        QUIT_KEY = k
                log(f"Hotkeys updated: record={RECORD_KEY} tone={TONE_KEY} layer={LAYER_KEY} stats={STATS_KEY} quit={QUIT_KEY}", "info")
            self._json({
                'record': RECORD_KEY.upper(),
                'tone': TONE_KEY.upper(),
                'layer': LAYER_KEY.upper(),
                'stats': STATS_KEY.upper(),
                'quit': QUIT_KEY.upper(),
            })
        elif self.path == '/api/transcribe':
            # Mobile PWA endpoint: accept base64 WAV, run pipeline, return text
            if not body or not isinstance(body.get('audio_b64'), str):
                self._json({"error": "Send {\"audio_b64\": \"...\"}"})
                return
            import base64
            tmp = None
            tmp2 = None
            try:
                audio_bytes = base64.b64decode(body['audio_b64'])
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.write(audio_bytes)
                tmp.close()
                audio_data, sr = sf.read(tmp.name)
                # Resample if needed
                if sr != TARGET_RATE:
                    from scipy.signal import resample_poly
                    import math
                    gcd = math.gcd(TARGET_RATE, sr)
                    audio_data = resample_poly(audio_data, TARGET_RATE // gcd, sr // gcd)
                # Flatten to mono if stereo
                if len(audio_data.shape) > 1:
                    audio_data = audio_data.mean(axis=1)
                # Audio preprocessing (same as main pipeline)
                audio_data = audio_data - numpy.mean(audio_data)  # DC removal
                nyq = TARGET_RATE / 2.0
                b_hp, a_hp = butter(2, 70.0 / nyq, btype="highpass")
                audio_data = filtfilt(b_hp, a_hp, audio_data).astype(numpy.float32)
                rms = numpy.sqrt(numpy.mean(audio_data ** 2))
                if rms > 1e-6:
                    target_rms = 10 ** (-12 / 20)
                    audio_data = audio_data * (target_rms / rms)
                audio_data = numpy.tanh(1.2 * audio_data).astype(numpy.float32)
                # Speech rate analysis (zero cost, informs reconstruction)
                speech_metrics = analyze_speech_rate(audio_data, TARGET_RATE)
                # Write resampled WAV
                tmp2 = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                sf.write(tmp2.name, audio_data, TARGET_RATE)
                tmp2.close()
                # Run Whisper
                t0 = time.time()
                whisper_result = whisper_transcribe(tmp2.name)
                raw_text = whisper_result["text"].strip()
                t_asr = time.time()
                if not raw_text:
                    self._json({"error": "No speech detected", "raw": "", "clean": ""})
                    return
                # Paralinguistic detection (Layer 5, zero API cost)
                para_events = detect_paralinguistic_events(
                    audio_data, TARGET_RATE, whisper_result.get("segments", []),
                    whisper_result.get("low_confidence"),
                    whisper_result.get("disagreements")
                )
                # Disfluency filter
                filtered = strip_disfluencies(raw_text)
                # Reconstruct (if layer >= 2)
                clean_text = filtered
                t_recon = t_asr
                if current_layer >= 2:
                    try:
                        clean_text = reconstruct(
                            filtered, current_tone, current_layer, profile,
                            whisper_low_conf=whisper_result.get("low_confidence"),
                            whisper_disagreements=whisper_result.get("disagreements"),
                            speech_severity_mod=speech_metrics["severity_modifier"],
                            paralinguistic_events=para_events if paralinguistic_enabled else None)
                    except Exception as e:
                        log(f"Mobile reconstruct failed: {e}", "error")
                        clean_text = filtered
                    t_recon = time.time()
                total_ms = round((t_recon - t0) * 1000)
                stats_inc("sessions")
                stats_inc("words", len(clean_text.split()))
                log(f"Mobile transcribe: {len(raw_text)}c -> {len(clean_text)}c ({total_ms}ms)", "info")
                self._json({
                    "raw": raw_text,
                    "filtered": filtered,
                    "clean": clean_text,
                    "layer": current_layer,
                    "tone": current_tone,
                    "total_ms": total_ms,
                })
            except Exception as e:
                log(f"Mobile transcribe failed: {e}", "error")
                self._json({"error": str(e)})
            finally:
                for f in (tmp, tmp2):
                    if f:
                        try: os.unlink(f.name)
                        except OSError: pass
        elif self.path == '/api/reconstruct_test':
            # Cross-platform parity test endpoint: feed raw text into pipeline, skip mic/Whisper.
            # POST {"raw": "I I I w-want to go", "tone": "casual", "layer": 2, "situation": "default"}
            # Returns same structure as mobile /api/transcribe but without audio path.
            if not body or not isinstance(body.get('raw'), str):
                self._json({"error": "Send {\"raw\": \"text\", \"tone\"?: \"...\", \"layer\"?: N, \"situation\"?: \"...\"}"})
                return
            try:
                import time as _t
                _t0 = _t.time()
                raw_text = body['raw']
                tone = body.get('tone', current_tone)
                layer = body.get('layer', current_layer)
                situation = body.get('situation', current_situation)
                # Strip disfluencies (same as main pipeline)
                filtered = strip_disfluencies(raw_text)
                clean_text = filtered
                falcon_ok = True
                if layer >= 2:
                    try:
                        clean_text = reconstruct(filtered, tone, layer, profile, situation=situation)
                    except Exception as e:
                        log(f"reconstruct_test failed: {e}", "error")
                        clean_text = filtered
                    # Falcon validation (SAFE mode)
                    try:
                        falcon_ok = falcon_validate(raw_text, clean_text, layer, tone)
                        if not falcon_ok:
                            clean_text = filtered
                    except Exception:
                        falcon_ok = True
                _ms = round((_t.time() - _t0) * 1000)
                # Compute WER
                raw_words = raw_text.lower().split()
                clean_words = clean_text.lower().split()
                _n, _m = len(raw_words), len(clean_words)
                if _n > 0:
                    dp = list(range(_m + 1))
                    for i in range(1, _n + 1):
                        prev, dp[0] = dp[0], i
                        for j in range(1, _m + 1):
                            cost = 0 if raw_words[i-1] == clean_words[j-1] else 1
                            dp[j], prev = min(dp[j]+1, dp[j-1]+1, prev+cost), dp[j]
                    wer = round(dp[_m] / _n, 4)
                else:
                    wer = 0.0
                self._json({
                    "raw": raw_text,
                    "filtered": filtered,
                    "clean": clean_text,
                    "tone": tone,
                    "layer": layer,
                    "situation": situation,
                    "falcon_ok": falcon_ok,
                    "wer": wer,
                    "recon_ms": _ms,
                    "pipeline": "lavrentiy",
                })
            except Exception as e:
                log(f"reconstruct_test error: {e}", "error")
                self._json({"error": str(e)})
        elif self.path == '/api/record':
            if is_recording:
                stop_recording()
                self._json({"recording": False})
            else:
                threading.Thread(target=start_recording, daemon=True).start()
                self._json({"recording": True})
        elif self.path == '/api/export-my-data':
            # GDPR: export all local + cloud data for signed-in user
            local_data = dict(profile)
            cloud_data = None
            if is_authenticated() and _firebase_id_token:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        BACKEND_URL,
                        data=json.dumps({"action": "export_data"}).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_firebase_id_token}"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        cloud_data = json.loads(resp.read()).get("data", {})
                except Exception as e:
                    log(f"Cloud export failed: {str(e)[:80]}", "warn")
            self._json({"local": local_data, "cloud": cloud_data, "user": _auth_user})
        elif self.path == '/api/delete-my-data':
            # GDPR: delete cloud data for signed-in user
            if not is_authenticated() or not _firebase_id_token:
                self._json({"error": "Not signed in"})
            else:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        BACKEND_URL,
                        data=json.dumps({"action": "delete_data"}).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_firebase_id_token}"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        resp.read()
                    log("Cloud data deleted", "info")
                    self._json({"ok": True, "deleted": True})
                except Exception as e:
                    log(f"Cloud delete failed: {str(e)[:80]}", "error")
                    self._json({"error": str(e)[:200]})
        elif self.path == '/api/reset-session-history':
            # Reset: clear session history (SQLite), keep learned profile intact
            try:
                with _db_lock:
                    _db.execute("DELETE FROM sessions")
                    _db.commit()
                with _stats_lock:
                    stats["words"] = 0
                    stats["sessions"] = 0
                    stats["chars"] = 0
                    stats["api_calls"] = 0
                    stats["falcon_rejects"] = 0
                    stats["repetition_loops"] = 0
                    stats["start_time"] = time.time()
                log("Session history reset — profile kept", "info")
                self._json({"ok": True, "reset": "session_history"})
            except Exception as e:
                log(f"Reset session failed: {e}", "error")
                self._json({"error": str(e)[:200]})
        elif self.path == '/api/delete-profile':
            # DELETE: wipe entire profile (corrections, vocabulary, triggers, everything)
            try:
                # Clear profile fields but preserve identity/structure
                profile["trigger_words"] = []
                profile["filler_words"] = []
                profile["vocabulary"] = []
                profile["corrections"] = {}
                profile["candidate_corrections"] = {}
                profile["candidate_fillers"] = {}
                profile["candidate_vocabulary"] = {}
                profile["covert_profile"] = {}
                profile["onset_weights"] = {}
                profile["onset_weights_by_lang"] = {}
                profile["trigger_types"] = {}
                profile["_relevance"] = {}
                save_profile(profile)
                # Also clear session history
                with _db_lock:
                    _db.execute("DELETE FROM sessions")
                    _db.commit()
                # Reset stats
                with _stats_lock:
                    for k in ("words", "sessions", "chars", "api_calls", "falcon_rejects", "repetition_loops"):
                        stats[k] = 0
                    stats["start_time"] = time.time()
                # Clear in-memory onset weights
                global _personal_onset_weights, _personal_onset_weights_by_lang, _personal_dominant_onsets
                _personal_onset_weights = {}
                _personal_onset_weights_by_lang = {}
                _personal_dominant_onsets = []
                log("Profile deleted — all learned data wiped", "warn")
                self._json({"ok": True, "reset": "profile"})
            except Exception as e:
                log(f"Delete profile failed: {e}", "error")
                self._json({"error": str(e)[:200]})
        elif self.path == '/api/augment':
            if _augment_state["running"]:
                self._json({"error": "augmentation already running", "status": augment_status()})
            else:
                # Run in background thread — TTS calls take a while
                threading.Thread(target=augment_calibration_data, daemon=True).start()
                self._json({"started": True, "status": augment_status()})
        elif self.path == '/api/patience':
            global PATIENCE_DEFAULT, PATIENCE_STUTTER
            if body:
                if 'default' in body:
                    try:
                        PATIENCE_DEFAULT = float(body['default'])
                    except (ValueError, TypeError):
                        pass
                if 'stutter' in body:
                    try:
                        PATIENCE_STUTTER = float(body['stutter'])
                    except (ValueError, TypeError):
                        pass
            self._json({"ok": True, "patience": get_patience_timeout(),
                        "default": PATIENCE_DEFAULT, "stutter": PATIENCE_STUTTER})
        elif self.path == '/api/set-key':
            global API_KEY, client
            key = (body or {}).get('key', '').strip()
            if key:
                API_KEY = key
                client = openai.OpenAI(api_key=API_KEY)
                try:
                    with open(_key_file, 'w') as f:
                        f.write(key)
                except Exception:
                    pass
                self._json({'ok': True})
            else:
                self._json({'ok': False, 'error': 'no key provided'})
        else:
            self.send_error(404)

    def _read_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except (ValueError, TypeError):
            return None
        # 10MB limit for audio uploads (transcribe, calibration)
        if length > 10_000_000:
            return None
        # Content-Length: 0 is valid for body-less POSTs (calibration/start, augment, etc.)
        # Return empty dict so callers can still do body.get("key") safely
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return None

    def _json(self, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        origin = self.headers.get('Origin', '')
        if origin in ('http://127.0.0.1:7878', 'http://localhost:7878', 'null'):
            self.send_header('Access-Control-Allow-Origin', origin)
        else:
            self.send_header('Access-Control-Allow-Origin', 'null')
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
        server = ThreadingHTTPServer(('0.0.0.0', DASHBOARD_PORT), DashboardHandler)
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
    idx = LAYERS.index(current_layer)
    set_layer(LAYERS[(idx + 1) % len(LAYERS)])
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

    # Only process KEY_DOWN for non-record keys (record/command need KEY_UP too)
    if event.event_type != keyboard.KEY_DOWN and event.name not in (RECORD_KEY, COMMAND_KEY):
        return

    if event.name == STATS_KEY and event.event_type == keyboard.KEY_DOWN:
        print_stats()
        return

    if event.name == TONE_KEY and event.event_type == keyboard.KEY_DOWN:
        cycle_tone()
        return

    if event.name == LAYER_KEY and event.event_type == keyboard.KEY_DOWN:
        cycle_layer()
        return

    if event.name == QUIT_KEY and event.event_type == keyboard.KEY_DOWN:
        now = time.time()
        tap_times = [t for t in tap_times if now - t < 0.8]
        tap_times.append(now)
        if len(tap_times) == 3:
            if _clipboard_predictor:
                _clipboard_predictor.stop()
            print("Lavrentiy out.")
            # Reset active_profile so the next cold start boots into Default.
            # atexit also covers this, but os._exit(0) bypasses atexit hooks —
            # write explicitly here.
            try:
                _write_active_profile_name(DEFAULT_PROFILE_NAME)
            except Exception:
                pass
            kernel32.CloseHandle(mutex_handle)
            os._exit(0)
        return

    if event.name == RECORD_KEY:
        # Ignore F9 events in first 3 seconds after startup (prevents ghost key)
        if time.time() - _hook_start_time < 3.0:
            return
        if event.event_type == keyboard.KEY_DOWN:
            if not is_recording:
                start_recording()
        elif event.event_type == keyboard.KEY_UP:
            stop_recording()

    if event.name == COMMAND_KEY:
        # Command Mode: highlighted text + spoken command → transformed text
        if time.time() - _hook_start_time < 3.0:
            return
        if event.event_type == keyboard.KEY_DOWN:
            if not is_recording and not is_command_mode:
                start_command_recording()
        elif event.event_type == keyboard.KEY_UP:
            if is_command_mode:
                stop_command_recording()

# -- Keep-alive (replaces tkinter indicator) ──────────────────────
def keep_alive():
    """Block main thread so the script stays running."""
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

# -- Main ─────────────────────────────────────────────────────────
_toggles = []
if paralinguistic_enabled: _toggles.append("para")
if prosodic_enabled: _toggles.append("prosodic")
_toggle_str = f" +{'+'.join(_toggles)}" if _toggles else ""
print(f"LAVRENTIY v0.1 | L{current_layer} {current_tone}{_toggle_str}")
print(f"Mic: {device_info['name']} | {NATIVE_RATE}Hz")
print(f"{RECORD_KEY.upper()}=talk  {TONE_KEY.upper()}=tone  {LAYER_KEY.upper()}=layer  {STATS_KEY.upper()}=stats  {QUIT_KEY.upper()}x3=quit")
print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
print(f"\"Lavrentiy does his best. Check your shit before you send it.\"")
print()

# Start dashboard server
threading.Thread(target=run_dashboard, daemon=True).start()

# Pre-warm Moonshine (loads ~250 MB ONNX into RAM) and Anthropic Haiku
# (TLS handshake + connection pool) at boot so the first user recording
# isn't a 15-30 second wait. Runs in a daemon thread — engine startup
# isn't blocked, but first F9 press finds both already warm.
def _prewarm_l1():
    try:
        # Moonshine warmup: synthesize 1 second of silence and run a transcribe.
        # Triggers _get_model() which loads encoder+decoder ONNX into memory.
        if _local_transcribe_fn is not None:
            import tempfile, soundfile as _sf, numpy as _np
            _silence = _np.zeros(16000, dtype=_np.float32)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as _tmp:
                _sf.write(_tmp.name, _silence, 16000)
                _tmp_path = _tmp.name
            try:
                _local_transcribe_fn(_tmp_path, 0.0, None, LANGUAGE, LOCAL_WHISPER_MODEL_SIZE)
                print("Moonshine pre-warmed")
            finally:
                try: os.unlink(_tmp_path)
                except OSError: pass
    except Exception as _e:
        print(f"Moonshine pre-warm failed (non-fatal): {str(_e)[:80]}")

def _prewarm_haiku():
    try:
        if anthropic_client is not None:
            anthropic_client.messages.create(
                model=FALCON_HAIKU_MODEL,
                max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            print("Haiku pre-warmed")
    except Exception as _e:
        print(f"Haiku pre-warm failed (non-fatal): {str(_e)[:80]}")

threading.Thread(target=_prewarm_l1, name="prewarm-moonshine", daemon=True).start()
threading.Thread(target=_prewarm_haiku, name="prewarm-haiku", daemon=True).start()

_hook_start_time = time.time()
# Open persistent audio stream so pre-roll buffer starts feeding immediately
try:
    _open_persistent_stream()
except Exception as e:
    log(f"Failed to open persistent stream: {e}", "error")
keyboard.hook(on_key_event)
keep_alive()
