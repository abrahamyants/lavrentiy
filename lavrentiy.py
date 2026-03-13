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
MODEL_L4 = "gpt-4o"                  # L4 stutter reconstruction uses stronger model
WHISPER_TEMP = 0.0                   # Whisper decoder temperature (0.0=deterministic, 1.0=creative)
WHISPER_NO_SPEECH_THRESHOLD = 0.15   # Post-hoc filter: segments with no_speech_prob > this are flagged as block suspects
                                     # OpenAI API doesn't expose no_speech_threshold — we filter client-side
                                     # using verbose_json no_speech_prob. Lower = preserve more blocks.
WHISPER_MULTI_TEMP = False           # Multi-temperature voting: OFF by default (3x cost, avg_logprob catches same artifacts)
WHISPER_MULTI_TEMPS = [0.0, 0.2, 0.4]  # Temperature schedule for voting passes
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
PROFILE_VERSION = 4

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
        log(f"Onset weights: dominant /{top['onset']}/ ({top['pct']}% of {total} triggers)", "info")


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
        log(f"Onset anomaly: /{top['onset']}/ at {top['actual_pct']}% vs expected {top['expected_pct']}% "
            f"(deficit {top['deficit_ratio']}x) — possible covert avoidance", "info")
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
            log(f"Profile v4: split {len(triggers)} triggers → en:{len(by_lang['en'])} ru:{len(by_lang['ru'])}", "info")
        normalize_profile(prof)
        prof["version"] = PROFILE_VERSION
        save_profile(prof)
    return prof

def log_session(prof, raw, output, tone, layer, decision=None, timings=None,
                situation=None, disf_counts=None, exposure=None, edit_dist=None,
                speech_metrics=None, lang=None):
    ts = datetime.now().isoformat()
    falcon = decision["falcon_ok"] if decision else True
    words = len(output.split())
    sit = situation or current_situation
    with _db_lock:
        _db.execute(
            "INSERT INTO sessions (ts, raw, out, tone, layer, words, falcon, decision, timings, "
            "situation, disfluency_counts, exposure_difficulty, editorial_distance, "
            "speech_metrics, lang) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, raw, output, tone, layer, words, int(falcon),
             json.dumps(decision) if decision else None,
             json.dumps(timings) if timings else None,
             sit,
             json.dumps(disf_counts) if disf_counts else None,
             json.dumps(exposure) if exposure else None,
             edit_dist,
             json.dumps(speech_metrics) if speech_metrics else None,
             lang or 'en')
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
# Migration: add disfluency_counts column
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN disfluency_counts TEXT")
except sqlite3.OperationalError:
    pass  # column already exists
# Migration: add exposure_difficulty and editorial_distance columns
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN exposure_difficulty TEXT")
except sqlite3.OperationalError:
    pass
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN editorial_distance REAL")
except sqlite3.OperationalError:
    pass
# Migration: add speech_metrics column (pause_ratio, rate, severity_modifier per session)
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN speech_metrics TEXT")
except sqlite3.OperationalError:
    pass
# Migration: add dominant language per session
try:
    _db.execute("ALTER TABLE sessions ADD COLUMN lang TEXT DEFAULT 'en'")
except sqlite3.OperationalError:
    pass
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
            "SELECT ts, raw, out, tone, layer, words, falcon, decision, timings, "
            "situation, disfluency_counts, exposure_difficulty, editorial_distance, "
            "speech_metrics, lang "
            "FROM sessions ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    result = []
    for row in rows:
        ts, raw, out, tone, layer, words, falcon, decision, timings, \
            situation, disf, exposure, edit_dist, spmet, lang = row
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
    "api_calls": 0, "falcon_rejects": 0,
    "multi_temp_votes": 0, "multi_temp_disagreements": 0
}

# -- Redo detection (anti-compulsion guardrail) ──────────────────
# Tracks consecutive re-recordings of similar content.
REDO_SIMILARITY_THRESHOLD = 0.7   # word overlap ratio to count as "same sentence"
REDO_NUDGE_THRESHOLD = 3          # redos before nudge
_redo_buffer = []                 # list of recent output word sets
_redo_count = 0                   # consecutive redo counter

def check_redo(output_text):
    """Check if this output is a redo of the previous recording.
    Returns redo count (0 = not a redo)."""
    global _redo_count
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

def log(text, kind="info"):
    global console_id
    console_id += 1
    console_log.append({"id": console_id, "ts": time.time(), "text": text, "kind": kind})
    if len(console_log) > 80:
        console_log.pop(0)
    print(text)

# -- LLM Calls ───────────────────────────────────────────────────
def reconstruct(raw_text, tone, layer, prof, situation=None,
                whisper_low_conf=None, whisper_disagreements=None,
                speech_severity_mod=0.0):
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

        # Inject Whisper confidence signals: low-confidence segments + multi-temp disagreements
        # avg_logprob targeting: where Whisper is uncertain near Brown risk = disfluency artifact
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
                parts.append(
                    "\n⚠ WHISPER UNCERTAINTY — these segments have low decoder confidence "
                    "AND high stuttering risk. They are almost certainly transcription artifacts:\n"
                    + "\n".join(lc_notes)
                    + "\nReconstruct aggressively. Trust semantic context, not the literal words."
                )
            if block_notes:
                parts.append(
                    "\n⚠ BLOCK SUSPECTS — Whisper nearly classified these as silence "
                    "(high no_speech_prob). For this speaker, silence before/during a word "
                    "is a BLOCK, not absence of speech. The text here is likely hallucinated "
                    "filler that Whisper invented to fill the gap:\n"
                    + "\n".join(block_notes)
                    + "\nDiscard these words entirely or replace with the word the speaker "
                    "was trying to say (use semantic context from surrounding words)."
                )
        # Multi-temperature voting: disagreements between decoding passes = garbled regions
        if whisper_disagreements:
            dis_notes = []
            for d in whisper_disagreements[:5]:
                variants = "/".join(set(d["variants"]))
                dis_notes.append(f"  position {d['position']}: [{variants}]")
            parts.append(
                "\n⚠ MULTI-PASS DISAGREEMENT — Whisper produced different words at these positions "
                "across 3 decoding temperatures. Disagreement = uncertain = likely disfluency artifact:\n"
                + "\n".join(dis_notes)
                + "\nThe truth is in the semantic context, not any single variant."
            )

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
            "\n\n=== FEW-SHOT EXAMPLES (by disfluency type) ==="
            "\n"
            "\nBLOCKS (silent fixation before word — Whisper may hallucinate or skip):"
            "\n  IN:  'I need the... [silence]... computer from the office'"
            "\n  OUT: 'I need the computer from the office'"
            "\n  IN:  'Can you get me the, the, the uh come put her from IT'"
            "\n  OUT: 'Can you get me the computer from IT'"
            "\n"
            "\nSOUND/SYLLABLE REPETITIONS (part-word):"
            "\n  IN:  'I was g-g-g-going to the st-store'"
            "\n  OUT: 'I was going to the store'"
            "\n  IN:  'Ca-ca-ca-can you p-p-please send the re-report'"
            "\n  OUT: 'Can you please send the report'"
            "\n"
            "\nWORD REPETITIONS:"
            "\n  IN:  'I I I want to to to go to the the meeting'"
            "\n  OUT: 'I want to go to the meeting'"
            "\n  IN:  'My my my mother uh my parents are coming'"
            "\n  OUT: 'My parents are coming'"
            "\n"
            "\nPROLONGATIONS (stretched sounds):"
            "\n  IN:  'I was thinking about the sssssschedule for next week'"
            "\n  OUT: 'I was thinking about the schedule for next week'"
            "\n  IN:  'We need to fffffinish this by Friday'"
            "\n  OUT: 'We need to finish this by Friday'"
            "\n"
            "\nFILLER STACKING + POSTPONEMENT:"
            "\n  IN:  'So um uh like basically uh the thing is we need more time'"
            "\n  OUT: 'We need more time'"
            "\n  IN:  'Can you give me the, uh, the paper for the thing you sign at the front desk'"
            "\n  OUT: 'Can you give me the form you sign at the front desk'"
            "\n"
            "\nAVOIDANCE / CIRCUMLOCUTION / ABANDONMENT:"
            "\n  IN:  'I need the b-... the document from yesterday'"
            "\n  OUT: 'I need the document from yesterday'"
            "\n  IN:  'I think of uh it's something the - you can't - that sort of thing'"
            "\n  OUT: [reconstruct intended meaning from surrounding context]"
            "\n  IN:  'The... oh never mind... yeah so anyway the other thing'"
            "\n  OUT: [recover abandoned thought if context allows, else skip]"
            "\n"
            "\nWHISPER ARTIFACTS (misheard stuttered speech):"
            "\n  IN:  'I was trying to come put her the file' (block on 'computer')"
            "\n  OUT: 'I was trying to compute the file' or 'I was trying to get the file'"
            "\n  IN:  'We but but blue print needs to be ready' (schwa corruption)"
            "\n  OUT: 'The blueprint needs to be ready'"
            "\n"
            "\n=== END EXAMPLES ==="
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

    use_model = MODEL_L4 if layer >= 4 else MODEL
    stats["api_calls"] += 1
    resp = client.chat.completions.create(
        model=use_model,
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
# Post-processing yields significant WER reduction on disfluent speech;
# combined with decoder tuning (Whisper prompt parameter), gains compound
# (informed by Stutter-TTS and Mujtaba "Inclusive ASR for Disfluent Speech").

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
    Returns list of {phrase, count} dicts for profile tracking."""
    if not text:
        return []
    loops = []
    # Match 2-4 word phrases repeated 3+ times (with optional comma/space between)
    # "I need to, I need to, I need to" or "I must I must I must"
    pattern = re.compile(
        r'\b((?:\w+[\s,]+){1,3}\w+)[,\s]+(?:\1[,\s]+){2,}',
        re.IGNORECASE
    )
    for m in pattern.finditer(text):
        phrase = re.sub(r'[,\s]+$', '', m.group(1)).strip()
        # Count how many times the phrase appears in the full match
        full = m.group(0)
        count = len(re.findall(re.escape(phrase), full, re.IGNORECASE))
        if count >= 3 and len(phrase.split()) >= 2:
            loops.append({"phrase": phrase.lower(), "count": count})
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

    # Component 2: Situational pressure
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


def set_last_prep(text):
    """Store the most recent Script Prep input for covert avoidance comparison."""
    global _last_prep_text, _last_prep_ts
    _last_prep_text = text.strip() if text else None
    _last_prep_ts = time.time()


def detect_covert_avoidance(actual_text, prof):
    """Compare actual speech against last Script Prep text to detect covert avoidance.
    Returns list of avoidance pairs: [{intended: word, said: word, onset: str}]
    Returns empty list if no prep text is available or it's expired."""
    global _last_prep_text
    if not _last_prep_text or not actual_text:
        return []
    # Check expiry
    if time.time() - _last_prep_ts > _PREP_EXPIRY_SEC:
        _last_prep_text = None
        return []

    prep_words = [w.lower() for w in re.findall(r'\b\w+\b', _last_prep_text)]
    actual_words = [w.lower() for w in re.findall(r'\b\w+\b', actual_text)]
    if not prep_words or not actual_words:
        return []

    # Build content-word sets (skip function words — they swap freely)
    prep_content = [w for w in prep_words if w not in FUNCTION_WORDS and len(w) > 2]
    actual_content = set(actual_words)

    # Find words that are in prep but NOT in actual speech
    missing = [w for w in prep_content if w not in actual_content]
    if not missing:
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
LEARN_EVERY = 3  # run learner every N sessions (Layer 2+)
DECAY_EVERY = 30             # run decay sweep every N sessions
DECAY_STALE_SESSIONS = 100   # corrections unused for this many sessions → demote to candidate
DECAY_DEAD_SESSIONS = 200    # candidates not re-seen for this many sessions → prune entirely
_learn_counter = 0
_decay_counter = 0
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
        learn_events.append({"ts": now, "type": "decay", "value": f"demoted: {key} → {value} (stale {DECAY_STALE_SESSIONS}+ sessions)"})
        log(f"Decay: demoted correction \"{key}\" → \"{value}\" (unused {DECAY_STALE_SESSIONS}+ sessions)", "info")
        demoted += 1

    # --- Candidates: prune entries that were demoted and never re-earned ---
    for key in list(cand_corr.keys()):
        entry = cand_corr[key]
        demoted_at = entry.get("demoted_at", 0)
        if demoted_at > 0 and session_n - demoted_at > DECAY_DEAD_SESSIONS:
            del cand_corr[key]
            learn_events.append({"ts": now, "type": "decay", "value": f"pruned candidate: {key}"})
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
        learn_events.append({"ts": now, "type": "decay", "value": f"demoted filler: {filler}"})
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
        learn_events.append({"ts": now, "type": "decay", "value": f"demoted vocab: {term}"})
        log(f"Decay: removed stale vocab \"{term}\" (unused {DECAY_STALE_SESSIONS}+ sessions)", "info")
        demoted += 1

    if demoted or pruned:
        save_profile(prof)
        log(f"Decay sweep: {demoted} demoted, {pruned} pruned (session #{session_n})", "info")

    return demoted + pruned


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


DISFLUENCY_TYPES = {
    "block", "sound_rep", "word_rep", "prolongation", "interjection",
    "avoidance", "loop_compulsion",
}


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
            # Per-language trigger bucket (#13)
            lang = detect_word_language(word)
            if lang in ("en", "ru"):
                by_lang = prof.setdefault("trigger_words_by_lang", {"en": [], "ru": []})
                by_lang.setdefault(lang, []).append(word)
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

# -- Whisper API (enhanced) ────────────────────────────────────────
def _build_whisper_prompt():
    """Build Whisper decoder prompt: Script Prep text (if available) + fluency bias.

    Script Prep as initial_prompt is the key insight: Whisper's autoregressive
    decoder treats the prompt as "previously transcribed text." When we seed it
    with the intended speech (from Script Prep), the decoder's beam search has
    the answer key before it transcribes. This dramatically reduces hallucination
    on blocked or disfluent segments.

    Falls back to generic fluency-biasing prompt when no Script Prep is available.
    """
    # Check if we have fresh Script Prep text (don't consume it — covert detection needs it too)
    if _last_prep_text and (time.time() - _last_prep_ts < _PREP_EXPIRY_SEC):
        # Whisper prompt has a ~224 token limit; truncate if needed
        prep = _last_prep_text[:500]
        log(f"Whisper seeded with Script Prep ({len(prep)} chars)", "info")
        return prep
    # No Script Prep — use fluency-biasing prompt
    return "Clear, fluent speech. Transcribe intended words only, not repetitions or filler sounds."


def _whisper_single_call(filepath, temperature, prompt_text):
    """Single Whisper API call returning verbose JSON with segment data.

    Returns dict with:
      text: full transcription
      segments: list of {text, avg_logprob, no_speech_prob, ...}
    """
    with open(filepath, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=LANGUAGE,
            prompt=prompt_text,
            temperature=temperature,
            response_format="verbose_json",
        )
    stats["api_calls"] += 1
    # OpenAI SDK returns a Transcription object; normalize to dict
    if hasattr(result, 'model_dump'):
        return result.model_dump()
    elif hasattr(result, '__dict__'):
        return result.__dict__
    return {"text": result.text if hasattr(result, 'text') else str(result), "segments": []}


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
        avg_lp = seg.get("avg_logprob", 0.0)
        no_speech = seg.get("no_speech_prob", 0.0)
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
        block_suspect = no_speech > WHISPER_NO_SPEECH_THRESHOLD

        # Flag if: low confidence AND near high-risk position, OR block suspect
        if avg_lp < risk_threshold or (avg_lp < -0.4 and brown_risk >= 0.5) or block_suspect:
            flagged.append({
                "text": seg_text,
                "avg_logprob": round(avg_lp, 3),
                "no_speech_prob": round(no_speech, 3),
                "position": words_so_far,
                "brown_risk": round(brown_risk, 2),
                "block_suspect": block_suspect,
            })
            if block_suspect:
                log(f"Block suspect: \"{seg_text}\" (no_speech_prob={no_speech:.2f}) — likely hallucinated over a block", "info")

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
    results = []
    for temp in WHISPER_MULTI_TEMPS:
        r = _whisper_single_call(filepath, temp, prompt_text)
        results.append(r)
        stats["multi_temp_votes"] += 1

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
        stats["multi_temp_disagreements"] += 1
        log(f"Multi-temp voting: {len(disagreements)} disagreements across {len(all_texts[0].split())} words", "info")

    return {
        "text": all_texts[0],  # temp=0 primary
        "segments": primary.get("segments", []),
        "disagreements": disagreements,
        "all_texts": all_texts,
    }


def whisper_transcribe(filepath):
    """Full Whisper transcription with all enhancements:
    1. Script Prep seeding (decoder conditioning)
    2. Verbose JSON mode (segment-level confidence)
    3. Multi-temperature voting (disagreement detection)

    Returns dict with:
      text: final transcription
      segments: verbose segment data
      low_confidence: flagged uncertain segments
      disagreements: multi-temp voting disagreements (if enabled)
      whisper_meta: {prompt_used, temperatures, n_api_calls}
    """
    prompt_text = _build_whisper_prompt()
    n_calls_before = stats["api_calls"]

    if WHISPER_MULTI_TEMP:
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

    return {
        "text": text,
        "segments": segments,
        "low_confidence": low_confidence,
        "disagreements": disagreements,
        "all_texts": all_texts,
        "whisper_meta": {
            "prompt_source": "script_prep" if (_last_prep_text and time.time() - _last_prep_ts < _PREP_EXPIRY_SEC) else "default",
            "prompt_length": len(prompt_text),
            "temperatures": WHISPER_MULTI_TEMPS if WHISPER_MULTI_TEMP else [WHISPER_TEMP],
            "n_api_calls": stats["api_calls"] - n_calls_before,
        }
    }


# -- Shadow Utterance (#12) ────────────────────────────────────
# "What you probably meant to say" — ground truth for avoidance measurement.
# For prepped text: Script Prep IS the shadow (zero cost).
# For unprepped text: one LLM call to infer intended speech from partial context.
# The diff between shadow and actual transcript = avoidance drift score.
# L4 only (extra API cost).

_shadow_history = []  # list of {ts, shadow, actual, drift_score, source}
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

        stats["api_calls"] += 1
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
    _shadow_history.append(entry)
    if len(_shadow_history) > _MAX_SHADOW_HISTORY:
        _shadow_history.pop(0)

    if drift_score > 0.15:
        log(f"Shadow drift: {drift_score:.0%} — {len(avoided)} words avoided [{source}]", "info")

    return entry


def compute_avoidance_trend():
    """Compute rolling avoidance drift trend from shadow history.
    Returns: avg drift over last 10 recordings, trend direction."""
    if not _shadow_history:
        return {"avg_drift": 0.0, "trend": "stable", "n": 0}
    recent = _shadow_history[-10:]
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

    # Step 0: Speech rate & pause analysis (pure numpy, zero cost)
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
            logprobs = [s.get("avg_logprob", 0) for s in whisper_segments if "avg_logprob" in s]
            _last_avg_logprob = round(sum(logprobs) / len(logprobs), 3) if logprobs else 0.0
        else:
            _last_avg_logprob = 0.0
        t_asr = time.time()
        if not raw_text:
            state = 'idle'
            return

        # Log Whisper pipeline details
        meta_tag = f"[{whisper_meta['prompt_source']}|{whisper_meta['n_api_calls']}calls]"
        if whisper_low_conf:
            meta_tag += f" low_conf:{len(whisper_low_conf)}"
        if whisper_disagreements:
            meta_tag += f" disagree:{len(whisper_disagreements)}"
        log(f"Whisper {meta_tag}", "info")

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
            # Pass Whisper confidence data so L4 can target uncertain segments
            try:
                clean_text = reconstruct(
                    filtered_text, current_tone, current_layer, profile, current_situation,
                    whisper_low_conf=whisper_low_conf,
                    whisper_disagreements=whisper_disagreements,
                    speech_severity_mod=speech_metrics["severity_modifier"]
                )
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
        disf_counts = count_disfluencies(raw_text)
        if disf_counts.get("total", 0) > 0:
            log(f"Disfluencies: {disf_counts}", "info")
        exposure = compute_exposure_difficulty(raw_text, current_situation, disf_counts, profile)
        edit_dist = compute_editorial_distance(raw_text, output)
        if exposure["score"] >= 0.4:
            log(f"Exposure: {exposure['band']} ({exposure['score']}) — triggers used: {exposure['components'].get('trigger_words_used', [])}", "info")
        # Redo detection (anti-compulsion)
        redo_n = check_redo(output)
        if redo_n >= REDO_NUDGE_THRESHOLD:
            log(f"Redo x{redo_n} — consider accepting this version and moving on", "info")
        # Shadow utterance (#12): generate "what you meant to say" (L4 only)
        # Must run BEFORE covert avoidance, which consumes _last_prep_text
        shadow_result = None
        if current_layer >= 4:
            shadow_result = generate_shadow_utterance(raw_text, profile)

        # Covert avoidance detection (Script Prep vs actual speech)
        covert_pairs = detect_covert_avoidance(raw_text, profile)
        if covert_pairs:
            update_covert_profile(profile, covert_pairs, current_situation)
            for cp in covert_pairs:
                log(f"Covert avoidance: \"{cp['intended']}\" → \"{cp['said']}\" (avoided /{cp['onset_avoided']}/)", "info")
        # Detect dominant language for this session (majority vote on words)
        _cyr_count = sum(1 for ch in raw_text if '\u0400' <= ch <= '\u04ff')
        _lat_count = sum(1 for ch in raw_text if ch.isalpha() and not ('\u0400' <= ch <= '\u04ff'))
        session_lang = 'ru' if _cyr_count > _lat_count else 'en'
        log_session(profile, raw_text, output, current_tone, current_layer, decision, timings,
                    disf_counts=disf_counts, exposure=exposure, edit_dist=edit_dist,
                    speech_metrics=speech_metrics, lang=session_lang)
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
        # Also: track profile relevance (zero cost) and run decay sweep periodically
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
                threading.Thread(target=learn_from_sessions, args=(profile,), daemon=True).start()
                # Onset anomaly detection (covert avoidance signal, zero API cost)
                all_sessions = db_get_sessions(limit=200)
                detect_onset_anomalies(all_sessions)

            # Decay sweep: prune stale corrections/fillers/vocab
            if _decay_counter >= DECAY_EVERY:
                _decay_counter = 0
                threading.Thread(target=decay_stale_profile_entries, args=(profile,), daemon=True).start()

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
                'stats': stats,
                'model': MODEL_L4 if current_layer >= 4 else MODEL,
                'whisper_temp': WHISPER_TEMP,
                'whisper_no_speech_threshold': WHISPER_NO_SPEECH_THRESHOLD,
                'whisper_multi_temp': WHISPER_MULTI_TEMP,
                'speech_metrics': _last_speech_metrics,
                'avg_logprob': _last_avg_logprob,
                'redo_count': _redo_count,
                'avg_exposure': self._compute_avg_exposure(),
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
                    'history': _shadow_history[-5:],  # last 5 for display
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
        elif self.path == '/api/severity':
            self._json(compute_severity_score())
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
                cp = profile.get('covert_profile', {})
                if sit in cp and 'substitutions' in cp[sit]:
                    if word in cp[sit]['substitutions']:
                        count = cp[sit]['substitutions'][word].get('count', 0)
                        del cp[sit]['substitutions'][word]
                        cp[sit]['total_events'] = max(0, cp[sit].get('total_events', 0) - count)
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
