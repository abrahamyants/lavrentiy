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
import sqlite3
import ctypes
import shutil
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
DASHBOARD_PORT = 7878
DB_PATH = PROFILE_DIR / "history.db"
DASHBOARD_PATH = PROFILE_DIR / "dashboard.html"

# -- Phase 2 config ──────────────────────────────────────────────
MODE = "SAFE"                     # RAW | FAST | SAFE (default)
MODES = ["RAW", "FAST", "SAFE"]
LEARN_PROMOTION_THRESHOLD = 2     # candidate recurrences before promotion
MAX_PROFILE_ITEMS = 200           # cap per profile section
HOLD_ON_HIGH_RISK = False         # True = skip paste when risk_flags present
BACKUP_DIR = PROFILE_DIR / "backups"
PROFILE_VERSION = 3

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
SITUATIONS = ["default", "phone", "presentation", "interview", "casual", "reading"]
SITUATION_SEVERITY = {
    "default":      1.0,
    "phone":        1.5,   # phone calls heavily exacerbate stuttering
    "presentation": 1.4,   # authority + audience + time pressure
    "interview":    1.6,   # max stress: authority + judgment + time pressure
    "casual":       0.6,   # friends/family, low pressure
    "reading":      0.3,   # reading aloud = near-fluent for most PWS
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
    # Affricates
    'ch', 'j',
    # High-risk consonant clusters
    'bl', 'br', 'cl', 'cr', 'dr', 'fl', 'fr', 'gl', 'gr',
    'pl', 'pr', 'sc', 'sk', 'sl', 'sm', 'sn', 'sp', 'st',
    'str', 'sw', 'tr', 'tw', 'thr', 'shr', 'scr', 'spl', 'spr',
}
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

# -- Personalized onset weights (learned from user's trigger history) ──
# Rebuilt whenever trigger_words changes. Maps onset -> 0.0-1.0 weight.
# Empty = no personal data yet, fall back to population priors.
_personal_onset_weights = {}
_personal_dominant_onsets = []  # top 3 onsets for insight display

def _extract_onset(word):
    """Extract the matching HIGH_RISK_ONSET from a word (longest match first)."""
    w = word.lower().strip()
    for length in (3, 2, 1):
        onset = w[:length]
        if onset in HIGH_RISK_ONSETS:
            return onset
    return None

def learn_onset_weights(trigger_words):
    """Analyze user's trigger words to learn which onsets they personally
    struggle with. Called when trigger_words list changes.

    Population prior: all high-risk onsets are equally dangerous (0.4).
    Personal model: onsets appearing in YOUR triggers get boosted
    proportional to their frequency. Onsets with zero personal evidence
    stay at the population floor.

    Example: triggers = [computer, conference, critical, create, class, break]
      onset counts: k=3, cr=1, cl=1, br=1  (total=6)
      k  -> freq 0.50 -> weight 0.65 (floor 0.4 + boost 0.25)
      cr -> freq 0.17 -> weight 0.48 (floor 0.4 + boost 0.08)
      Unseen onsets -> weight 0.3 (below population prior = deprioritized)

    Inspired by Ghai & Mueller (ASSETS '21) — phonetic pattern learning."""
    global _personal_onset_weights, _personal_dominant_onsets
    if not trigger_words:
        _personal_onset_weights = {}
        _personal_dominant_onsets = []
        return

    onset_counts = {}
    for word in trigger_words:
        onset = _extract_onset(word)
        if onset:
            onset_counts[onset] = onset_counts.get(onset, 0) + 1

    if not onset_counts:
        _personal_onset_weights = {}
        _personal_dominant_onsets = []
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

    # Track dominant onsets for insights (top 3 by count)
    ranked = sorted(onset_counts.items(), key=lambda x: -x[1])
    _personal_dominant_onsets = [
        {"onset": onset, "count": count, "pct": round(count / total * 100)}
        for onset, count in ranked[:3]
    ]
    if _personal_dominant_onsets:
        top = _personal_dominant_onsets[0]
        log(f"Onset weights: dominant /{top['onset']}/ ({top['pct']}% of {total} triggers)", "info")


def predict_phonetic_risk(word):
    """Predict block risk for a word based on phonetic onset + word type.
    Returns 0.0-1.0 risk score. Uses personalized onset weights when
    available (learned from user's trigger history), falls back to
    population priors when no personal data exists."""
    w = word.lower().strip()
    if not w or w in FUNCTION_WORDS:
        return 0.1  # function words rarely trigger
    score = 0.3  # base risk for content words
    # Check onset against high-risk patterns (longest match first)
    matched_onset = None
    for length in (3, 2, 1):
        onset = w[:length]
        if onset in HIGH_RISK_ONSETS:
            matched_onset = onset
            break
    if matched_onset:
        if _personal_onset_weights:
            # Personalized: user's onset gets learned weight, unseen gets 0.3
            score += _personal_onset_weights.get(matched_onset, 0.3)
        else:
            # No personal data yet — population prior: all onsets equal
            score += 0.4
    # Unvoiced consonants are harder than voiced
    if w[0] in 'ptksf':
        score += 0.1
    return min(score, 1.0)

def predict_triggers_in_text(text, existing_triggers):
    """Score all content words in text, return predicted triggers above threshold.
    Combines phonetic prior with user's known trigger history."""
    words = set(text.lower().split())
    known = {t.lower() for t in existing_triggers}
    predicted = []
    for word in words:
        clean = re.sub(r'[^\w]', '', word)
        if not clean or len(clean) < 2:
            continue
        risk = predict_phonetic_risk(clean)
        # Boost if the word shares an onset with a known trigger
        for trigger in known:
            if trigger[:2] == clean[:2] and clean != trigger:
                risk = min(risk + 0.2, 1.0)
                break
        if risk >= 0.6:
            predicted.append((clean, round(risk, 2)))
    return sorted(predicted, key=lambda x: -x[1])

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
    "preferences": {"tone": "casual", "layer": 2}
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
        normalize_profile(prof)
        prof["version"] = PROFILE_VERSION
        save_profile(prof)
    return prof

def log_session(prof, raw, output, tone, layer, decision=None, timings=None, situation=None):
    ts = datetime.now().isoformat()
    falcon = decision["falcon_ok"] if decision else True
    words = len(output.split())
    sit = situation or current_situation
    with _db_lock:
        _db.execute(
            "INSERT INTO sessions (ts, raw, out, tone, layer, words, falcon, decision, timings, situation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, raw, output, tone, layer, words, int(falcon),
             json.dumps(decision) if decision else None,
             json.dumps(timings) if timings else None,
             sit)
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
        # Save transcript pair
        meta = {
            "timestamp": datetime.now().isoformat(),
            "raw_whisper": raw_text,
            "corrected_output": output_text,
            "layer": layer,
            "situation": situation,
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
    # Run through Whisper to capture raw ASR for WER comparison
    whisper_raw = ""
    try:
        with open(str(wav_path), "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f, language=LANGUAGE
            )
        whisper_raw = result.text.strip()
        stats["api_calls"] += 1
    except Exception as e:
        log(f"Calibration Whisper pass failed: {e}", "error")
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


# -- Synthetic disfluency augmentation (Mujtaba24 Interspeech) ──
import random
import base64

AUGMENT_DIR = CALIBRATION_DIR / "augmented"
AUGMENT_VARIANTS = 4              # synthetic variants per real sample
AUGMENT_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
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
                stats["api_calls"] += 1

                # Run through Whisper to capture how ASR handles the disfluent audio
                whisper_raw = ""
                try:
                    with open(str(wav_path), "rb") as f:
                        w_result = client.audio.transcriptions.create(
                            model="whisper-1", file=f, language=LANGUAGE
                        )
                    whisper_raw = w_result.text.strip()
                    stats["api_calls"] += 1
                except Exception as e:
                    log(f"Augment Whisper pass failed for {base}: {e}", "error")

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

# -- SQLite session history ───────────────────────────────────────
PROFILE_DIR.mkdir(exist_ok=True)
_db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
_db.execute("PRAGMA journal_mode=WAL")
_db.execute("PRAGMA synchronous=NORMAL")
_db.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        raw TEXT NOT NULL,
        out TEXT NOT NULL,
        tone TEXT NOT NULL,
        layer INTEGER NOT NULL,
        words INTEGER NOT NULL,
        falcon INTEGER NOT NULL DEFAULT 1,
        decision TEXT,
        timings TEXT,
        situation TEXT DEFAULT 'default'
    )
""")
_db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(ts)")
# Migration: add situation column to existing DBs
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN situation TEXT DEFAULT 'default'")
except sqlite3.OperationalError:
    pass  # column already exists
_db.commit()
_db_lock = threading.Lock()

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
            "SELECT ts, raw, out, tone, layer, words, falcon, decision, timings, situation "
            "FROM sessions ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    result = []
    for ts, raw, out, tone, layer, words, falcon, decision, timings, situation in rows:
        entry = {"ts": ts, "raw": raw, "out": out, "tone": tone,
                 "layer": layer, "words": words, "falcon": bool(falcon),
                 "situation": situation or "default"}
        if decision:
            entry["decision"] = json.loads(decision)
        if timings:
            entry["timings"] = json.loads(timings)
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
def reconstruct(raw_text, tone, layer, prof, situation=None):
    """Layer 2+: Rebuild raw transcription into clean output."""
    # Detect if input contains Cyrillic (bilingual speaker)
    has_cyrillic = any('\u0400' <= c <= '\u04ff' for c in raw_text)
    lang_note = " Speaker is bilingual (English/Russian) and may mix languages." if has_cyrillic else ""

    # Situational aggressiveness — higher stress = more aggressive cleanup
    sit = situation or current_situation
    severity = SITUATION_SEVERITY.get(sit, 1.0)
    aggression_note = ""
    if severity >= 1.4:
        aggression_note = (
            " Speaker is in a HIGH-STRESS context (phone/presentation/interview). "
            "Expect more disfluencies, heavier avoidance, more filler stacking. "
            "Be MORE aggressive in reconstructing — strip more, trust less of the literal words."
        )
    elif severity <= 0.6:
        aggression_note = (
            " Speaker is in a low-stress context. Expect near-fluent speech. "
            "Be conservative — minor cleanup only."
        )

    parts = [
        f"Rebuild this raw voice transcription into clean {tone} text.{lang_note}{aggression_note}",
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
            "\nThe speaker stutters. Raw transcription is evidence, not truth. "
            "Reconstruct intended meaning, not literal word sequence."
            "\n\nOvert disfluencies — strip and reconstruct:"
            "\n- Part-word repetitions: 'b-b-b-buy' → 'buy', 'Ca-ca-ca-can' → 'Can'"
            "\n- Whole-word repetitions: 'I I I want' → 'I want', 'I want... I want to go' → 'I want to go'"
            "\n- Prolongations: 'mmmmaybe' → 'maybe', 'Sssssscience' → 'Science'"
            "\n- Schwa substitution: 'guh-guh-goat' → 'goat' (neutral /ə/ replaces natural vowel in repeats)"
            "\n- Consonant cluster breaks: failed blends inject schwa, e.g. 'bə-bə-blue' → 'blue'"
            "\n- Blocks: silence or frozen onset before a word (locked articulators, no sound)"
            "\n- Tremors: lip/jaw quivering during a fixation"
            "\n- Secondary behaviors: eye blinks, foot taps, head movements during blocks"
            "\n- False starts and restarts"
            "\n\nCovert stuttering — recognize as avoidance, not content:"
            "\n- Filler clusters before a content word = delay tactic (starters), not hesitation"
            "\n- Synonym substitution = avoiding a feared word"
            "\n- Circumlocution = talking around a feared word"
            "\n- Sentence abandonment = dropping thought before feared word ('Oh, never mind')"
            "\n- Covert interruption = jumping in while someone talks to mask onset difficulty"
            "\n- Mazes/cluttering = rambling run-on filler adding no information"
            "\n  e.g. 'I think of uh - it's something you say as it comes out of - that sort of thing'"
            "\n- Pause before a word = anticipatory fear (scanning ahead), not thinking"
            "\n\nPhonetic triggers (common block locations — 90%+ occur on initial sounds):"
            "\n- Stop plosives: /p/, /b/, /t/, /d/, /k/, /g/ (unvoiced > voiced)"
            "\n- Affricates: /tʃ/, /dʒ/"
            "\n- Consonant clusters at onset: bl-, br-, cr-, str-, spl-, thr-, etc."
            "\n- Initial position of words and clauses (clause boundary = high risk)"
            "\n- Content words (nouns, verbs, adjectives) >> function words (articles, conjunctions)"
            "\n- Consonant-vowel transitions (speaker starts vowel but can't coarticulate to next sound)"
            "\n\nAnticipatory behavior (cognitive pattern — CRITICAL):"
            "\n- A pause or silence BEFORE a content word is likely ANTICIPATORY FEAR, not thinking"
            "\n- The speaker scans ahead, detects a feared word coming, and freezes"
            "\n- Ellipsis, trailing off, or sudden topic change before a specific word = avoidance"
            "\n- 'I need the... uh... that thing' = speaker feared the next word, not searching for it"
            "\n- Treat pre-word pauses on content words as blocks, not as natural hesitation"
            "\n\nWhisper ASR failure modes on stuttered speech (correct these artifacts):"
            "\n- HALLUCINATION DURING BLOCKS: silence/frozen onset → Whisper invents words to fill the gap"
            "\n  e.g. block before 'computer' → Whisper outputs 'come to' or 'come put her'"
            "\n- SYLLABLE DELETION: repeated syllables get collapsed or dropped"
            "\n  e.g. 'Ca-ca-ca-can I' → Whisper outputs 'Can I' (correct) or just 'I' (dropped too much)"
            "\n- PHANTOM INSERTIONS: during prolongations, Whisper hallucinates phonetically similar words"
            "\n  e.g. 'sssscience' → Whisper outputs 'signs' or 'silence'"
            "\n- SCHWA CORRUPTION: neutral vowel in repeated clusters gets transcribed as a real word"
            "\n  e.g. 'buh-buh-blue' → Whisper outputs 'but but blue' or 'above blue'"
            "\n- PAUSE HALLUCINATION: long pauses → Whisper generates filler text, thanks, or topic shifts"
            "\n  e.g. 3-second block → Whisper adds 'Thank you' or 'Okay' or repeats the previous phrase"
            "\n- WORD BOUNDARY ERRORS: disfluent onset merged with previous word"
            "\n  e.g. 'the c-c-contract' → Whisper outputs 'the contract' (fine) or 'they contract' (merged)"
            "\nIf a word seems phonetically plausible but semantically wrong, suspect a Whisper artifact."
            "\n\nExamples:"
            "\n- 'Can you give me the, uh, the paper for the thing you sign "
            "at the front desk' → 'Can you give me the form you sign at the front desk'"
            "\n- 'My... my... my mother, uh, my parents are coming' → 'My parents are coming'"
            "\n- 'I need the b-... the document from yesterday' → 'I need the document from yesterday'"
            "\n- 'I think of uh it's something the - you can't - that sort of thing' "
            "→ reconstruct the intended meaning from context"
            "\n\nDo not mistake disfluency for emphasis. "
            "Do not invent meaning beyond what was intended. "
            "When uncertain, prefer conservative cleanup over aggressive rewriting."
        )
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
            "Speaker stutters. Repeated syllables, prolongations, and blocks are "
            "disfluencies, not emphasis. Filler clusters before content words are "
            "postponement tactics, not meaningful hesitation. Synonym substitutions "
            "and circumlocutions are avoidance behaviors — the reconstruction should "
            "recover the intended word. Rambling run-on filler (mazes) should be "
            "stripped. Does the reconstruction preserve intended meaning? "
            "Answer ONLY 'yes' or 'no'."
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


# -- Disfluency post-filter (rule-based, zero API cost) ────────
# Research shows 28.7% WER reduction from simple post-processing;
# 61.2% combined with decoder tuning (Whisper prompt parameter).

# Common fillers to strip (bilingual EN/RU)
_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}

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
    cleaned = re.sub(r'\b(\w+)(?:\s+\1)+\b', r'\1', cleaned, flags=re.IGNORECASE)

    # Step 3: Remove phrase repetitions (2-3 word phrases repeated)
    # "I want I want to go" → "I want to go"
    cleaned = re.sub(
        r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', r'\1', cleaned, flags=re.IGNORECASE
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


# -- Script Prep (pre-speech word substitution, Ghai & Mueller ASSETS '21)
def prep_text(text, prof):
    """Analyze text the user is about to speak. Flag high-risk words and
    suggest phonetically safer synonyms. Returns list of flagged words
    with alternatives."""
    if not text or not text.strip():
        return {"words": [], "flagged": []}

    triggers = prof.get("trigger_words", [])
    trigger_set = {t.lower() for t in triggers}
    # Score every word
    words = re.findall(r'\b\w+\b', text)
    scored = []
    for w in words:
        risk = predict_phonetic_risk(w)
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

    stats["api_calls"] += 1
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

    return {"words": scored, "flagged": flagged}


# -- Auto-Learn ──────────────────────────────────────────────────
LEARN_EVERY = 3  # run learner every N sessions (Layer 2+)
_learn_counter = 0
learn_events = []  # [{ts, type, value}, ...]
learn_status = {"last_run": None, "total_learned": 0, "next_in": LEARN_EVERY}

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
                learn_events.append({"ts": now, "type": "candidate", "value": f"{wrong}: tie ({entry['total']} votes), held"})
                log(f"Candidate tie: \"{wrong}\" — not promoted", "info")
            else:
                winner = ranked[0][0]
                if len(prof.get("corrections", {})) < MAX_PROFILE_ITEMS:
                    prof.setdefault("corrections", {})[wrong] = winner
                del cand_corr[key]
                learn_events.append({"ts": now, "type": "correction", "value": f"{wrong} → {winner}"})
                log(f"Promoted: \"{wrong}\" → \"{winner}\"", "info")
                promoted += 1
        else:
            learn_events.append({"ts": now, "type": "candidate", "value": f"{wrong} → {right} ({entry['total']}/{LEARN_PROMOTION_THRESHOLD})"})

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
            learn_events.append({"ts": now, "type": "filler", "value": key})
            log(f"Promoted filler: \"{filler}\"", "info")
            promoted += 1
        else:
            learn_events.append({"ts": now, "type": "candidate", "value": f"filler: {key} ({cand_fill[key]}/{LEARN_PROMOTION_THRESHOLD})"})

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


DISFLUENCY_TYPES = {"block", "sound_rep", "word_rep", "prolongation", "interjection", "avoidance"}


def detect_triggers_llm(raw_text, output, prof):
    """LLM-assisted trigger word detection with disfluency type classification.
    Async, Layer 4 only. Returns dict: {word: disfluency_type}."""
    stats["api_calls"] += 1
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
            # Store disfluency type
            trigger_types[word.lower()] = dtype
            learn_events.append({
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
    recent_triggers = sum(1 for e in learn_events if e.get("type") == "trigger")
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
            _daf_stream.stop()
            _daf_stream.close()
            _daf_stream = None
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
        # Step 1: Whisper (with stutter-aware prompt to bias decoder)
        t0 = time.time()
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f, language=LANGUAGE,
                prompt="Clear, fluent speech. Transcribe intended words only, not repetitions or filler sounds."
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

        # Step 1.5: Disfluency post-filter (rule-based, zero cost)
        # At L1: this IS the output cleanup (no GPT reconstruction)
        # At L2+: pre-cleans Whisper output before sending to GPT
        filtered_text = strip_disfluencies(raw_text)
        if filtered_text != raw_text and current_layer == 1:
            log(f"Filter: \"{raw_text}\" → \"{filtered_text}\"", "info")

        if current_layer > 1 and current_mode != "RAW":
            log(f"Raw: \"{raw_text}\"", "raw")

            # Step 2: Reconstruct (using pre-cleaned text to reduce GPT noise)
            try:
                clean_text = reconstruct(filtered_text, current_tone, current_layer, profile, current_situation)
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

        # Step 7: Archive audio for future Whisper fine-tuning
        # Runs synchronously — must complete before finally{} deletes tmp
        if current_layer >= 2 and raw_text and output:
            archive_session_audio(tmp.name, raw_text, output, current_layer, current_situation)

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

def set_situation(situation):
    global current_situation
    if situation in SITUATIONS:
        current_situation = situation
        severity = SITUATION_SEVERITY[situation]
        log(f"Situation: {situation} (severity: {severity}x)", "info")

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
                'situation': current_situation,
                'situation_severity': SITUATION_SEVERITY.get(current_situation, 1.0),
                'stats': stats
            })
        elif self.path == '/api/profile':
            self._json(profile)
        elif self.path == '/api/sessions':
            self._json(db_get_sessions(limit=50))
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
                },
                'insights': build_stutter_insights(profile) if current_layer >= 4 else [],
                'insights_enabled': current_layer >= 4,
                'onset_weights': {
                    'personal': _personal_onset_weights,
                    'dominant': _personal_dominant_onsets,
                    'has_data': bool(_personal_onset_weights),
                }
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
        elif self.path == '/api/preview':
            with preview_lock:
                self._json({
                    'enabled': LIVE_PREVIEW_ENABLED,
                    'active': preview_state['active'],
                    'text': preview_state['text'],
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
        elif self.path == '/api/situation':
            if body and isinstance(body.get('situation'), str):
                set_situation(body['situation'].lower())
            self._json({
                'situation': current_situation,
                'severity': SITUATION_SEVERITY.get(current_situation, 1.0),
                'situations': SITUATIONS
            })
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
        elif self.path == '/api/prep':
            if body and isinstance(body.get('text'), str):
                result = prep_text(body['text'], profile)
                self._json(result)
            else:
                self._json({"error": "Send {\"text\": \"your script here\"}"})
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
                try:
                    audio_bytes = base64.b64decode(body['audio_b64'])
                    # Write to temp file, read back as numpy array
                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp.write(audio_bytes)
                    tmp.close()
                    audio_data, sr = sf.read(tmp.name)
                    os.unlink(tmp.name)
                    result = calibration_save_audio(int(body['prompt_id']), audio_data, sr)
                    result["next_prompt"] = calibration_next_prompt()
                    result["status"] = calibration_status()
                    self._json(result)
                except Exception as e:
                    log(f"Calibration record failed: {e}", "error")
                    self._json({"error": str(e)})
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
        elif self.path == '/api/augment':
            if _augment_state["running"]:
                self._json({"error": "augmentation already running", "status": augment_status()})
            else:
                # Run in background thread — TTS calls take a while
                threading.Thread(target=augment_calibration_data, daemon=True).start()
                self._json({"started": True, "status": augment_status()})
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
