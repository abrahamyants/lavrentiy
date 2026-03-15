# LAVRENTIY — Owner's Manual

## Starting the Engine
Double-click **Lavrentiy Dashboard.vbs** on your Desktop. It launches the Python engine headless and opens Edge in app mode at `localhost:7878`. No console window.

---

## The Sidebar (Left Panel)

### Brand + Status LED
The small dot in the upper-right corner of the brand area:
- **Green** — idle, ready for input
- **Red pulsing** — recording your voice
- **Yellow** — processing (Whisper + reconstruction)

### Compact Toggle `⊟` / `⊞`
Upper-right of the brand. Collapses the full dashboard into a single-line status bar (compact mode). Click again to expand. Useful when you want Lavrentiy running but out of the way.

### Status Ring
The circular gauge below the brand. Shows:
- **State label** — IDLE / RECORDING / PROCESSING
- **Uptime** — how long the engine has been running (MM:SS)
- The ring **spins red** while recording, **yellow** while processing, **green tick** at idle.

### Tone (4 buttons)
Controls the voice/register of LLM reconstruction. Only matters at Layer 2+.
| Button | What it does |
|--------|-------------|
| **Casual** | Everyday language, contractions OK |
| **Professional** | Clean business English |
| **Friend** | Relaxed, informal |
| **Formal** | Stiff, precise, no contractions |

Active button glows red with a green LED dot. The engine uses this tone when the LLM rewrites your speech.

### Layer (4 buttons)
Controls how much processing your speech gets. Each layer adds to the previous:
| Layer | Name | What happens |
|-------|------|-------------|
| **1** | Transcribe | Whisper STT only — raw text, no cleanup |
| **2** | Reconstruct | LLM rewrites with selected tone |
| **3** | Profile | + your personal vocabulary, corrections, trigger words |
| **4** | Stutter | + disfluency filtering, OCD loop detection, phonetic risk, all insights |

### Mode (3 buttons)
Controls the safety pipeline:
| Mode | What happens |
|------|-------------|
| **RAW** | No validation — paste whatever comes out |
| **FAST** | Single-pass LLM, no Falcon check |
| **SAFE** | Full pipeline: reconstruct → Falcon validate → risk flags → decision |

### Situation (6 buttons)
Presets that tune severity multiplier and auto-configure other settings:
| Situation | Severity | Auto-config |
|-----------|----------|-------------|
| **Default** | 1.0× | Baseline |
| **Casual** | 0.6× | Relaxed thresholds |
| **Phone** 🔥 | 1.5× | DAF 100ms + Layer 4 + Prep |
| **Present** ⚡ | 1.4× | Layer 4 + Prep |
| **Interview** ⚡ | 1.6× | DAF 80ms + Layer 4 + Prep |
| **Reading** | 0.3× | Layer 3 (minimal intervention) |

Higher severity = more aggressive disfluency filtering and reconstruction. The 🔥/⚡ buttons auto-enable DAF, Layer 4, and Prep mode.

### DAF (Delayed Auditory Feedback)
- **Toggle switch** — turns DAF on/off (red = on)
- **Dial** — drag to adjust delay (30–300ms, shown below dial)
- DAF plays your own voice back to you with a slight delay. Classic fluency technique. 100ms is a good starting point.

### Whisper Section (upper)
| Readout | Meaning |
|---------|---------|
| **MULTI-TEMP** toggle | When ON, runs Whisper at 3 temperatures and votes on the best result. 3× API cost but better accuracy on stuttered speech |
| **PREP SEED** | Shows whether Script Prep text is being fed to Whisper as decoder context ("seeded" vs "—") |
| **BLOCKS** | Count of detected speech blocks (prolonged silence where you tried to speak) |

### Speech Section
Real-time speech metrics from your last utterance:
| Readout | Meaning |
|---------|---------|
| **PAUSE** | Pause ratio — % of your recording that was silence. >60% = red (lots of blocking), >40% = yellow |
| **RATE** | Speaking rate in syllables/second. <2 syl/s = yellow (unusually slow, possible blocking) |
| **SEVERITY+** | Dynamic severity modifier added on top of your situation preset based on speech metrics. +1 means speech patterns suggest you're struggling more than usual |

Below these, when data exists, a **severity breakdown** appears showing: `base + speech_modifier = final [BAND]`

### Whisper Section (lower)
| Control/Readout | Meaning |
|-----------------|---------|
| **NO_SPEECH** slider | Whisper's `no_speech_threshold` (0.05–0.80). Higher = more aggressive silence rejection. Red if >0.5 |
| **AVG LOGPROB** | Whisper's average log probability for the last transcription. Lower (more negative) = less confident. Red if < -0.7 |
| **REDOS** | How many times you re-recorded the same utterance. ≥3 = red (OCD replay lockout territory) |

### Hotkeys Section
Click the section title to expand. Shows current key bindings:
| Default | Action |
|---------|--------|
| **F9** | Start/stop recording |
| **F10** | Cycle through tones |
| **F11** | Cycle through layers |
| **F12** | Print stats to console |
| **F3** ×3 | Quit (press 3 times) |

Click the ⚙ button next to any key, then press your desired key to rebind. Click **Save to Engine** to persist.

### Sidebar Footer
Speaker grille with the Marshall-style "Лаврентий" badge. Shows hotkey quick-reference below.

---

## Top Stats Row (6 cells)

Dark LED-style readout panels across the top of the main area:

| Cell | What it shows |
|------|--------------|
| **Words** | Total words processed this session |
| **Sessions** | Number of transcription sessions (one press of F9 = one session) |
| **WPM** | Average words per minute since engine start |
| **API Calls** | Total OpenAI API calls (Whisper + LLM) |
| **Avg Difficulty** | Average exposure difficulty from last 20 sessions. Color-coded: green (low) → yellow (moderate) → red (high/very high) |
| **Est. Cost** | Estimated API cost this session (~$0.0032 per session) |

---

## Learn Bar Row (second row)

Smaller readout cells showing your profile's learning state:

| Cell | What it shows |
|------|--------------|
| **Corrections** | How many Whisper→correct mappings the engine has learned (e.g., "Duncan" → "Dankeschön") |
| **Fillers** | Filler words identified and added to your profile |
| **Vocabulary** | Preferred terms the engine has learned |
| **Triggers** | Known trigger words (words you stutter on) |
| **Edit Dist** | Average editorial distance between raw and reconstructed text. Higher = more changes being made. Red >0.4 |
| **Redos** | Redo count — how many times you re-did the same utterance. Red ≥3 (OCD lockout watch) |
| **Next cycle** | Progress bar toward the next auto-learning sweep (every 3 sessions) |
| **Decay** | Progress bar toward the next correction decay sweep — old corrections that stop appearing get pruned |

---

## Tabs (8 tabs)

### 1. Console
Live log output from the engine. Color-coded:
- **Green** — recording events
- **Gray** — raw transcription
- **White** — reconstructed output
- **Yellow** — info messages
- **Red** — errors

A **PREVIEW** bar appears at the top while recording, showing live trigger-risk words highlighted in yellow (risky) or red (high-risk).

### 2. Sessions
Card feed of all transcriptions this session. Each card shows:
- **Timestamp** + editorial distance (Δ)
- **Tags**: mode, layer (L1–L4), tone (CAS/PRO/FRD/FRM), situation (PHN/PRS/INT), exposure band, Falcon OK/REJ, processing time (ms), risk flags
- **RAW** line — what Whisper heard (shown only when different from output)
- **OUT** line — final reconstructed text

### 3. Learning
Feed of everything the engine has learned, newest first. Each event is tagged:
- **CORR** (yellow) — correction learned
- **FILLER** (red) — filler word detected
- **VOCAB** (green) — vocabulary term learned
- **TRIGGER** (purple) — trigger word identified
- **CAND** (gray) — candidate (needs confirmation)
- **DECAY** (orange) — correction decayed/pruned

At the bottom: **WEEKLY REPORT** button generates a clinical-style summary of your speech patterns.

### 4. Insights
Speech analytics (requires Layer 4). Shows insight cards with severity badges (HIGH/MEDIUM/LOW) plus:

- **Phoneme Difficulty Map** — bar chart of your personal onset weights. Taller/redder bars = harder sounds for you
- **Covert Avoidance Patterns** — words you're avoiding and what you substitute (e.g., "computer" → "laptop")
- **Onset Anomalies** — sounds you use significantly less than expected (possible avoidance)
- **Per-Language Onset Weights** — separate difficulty maps for English vs Russian
- **Substitution Fingerprint** — your avoidance index (0–100%), most avoided onsets, top substitution pairs, drift alerts for new emerging patterns
- **Avoidance Drift** — tracks how much your actual speech drifts from what you intended (prep text vs. actual). Trend: increasing/stable/decreasing
- **Low Confidence Segments** — Whisper segments with low avg_logprob near Brown-risk positions. `BLOCK?` tag = suspected speech block
- **Fluency Trend** — sparkline of pause ratio over your last 30 sessions. Shows avg pause, avg rate, avg severity modifier, trend direction (improving/stable/worsening), language distribution (EN/RU split)

### 5. Prep (Script Preparation)
Paste text you're about to say (email, talking points, presentation script). Click **PREP**.

Words get color-coded:
- **Gray** — safe, no risk
- **Light red** — risky onset (phonetically difficult based on your profile)
- **Bold red** — known trigger word (you've stuttered on this before)

**Hover** on a risky/trigger word to see **synonym alternatives** — click one to swap it in-place.

When prepped, a green badge appears: **"WHISPER SEEDED — decoder will use this text as context"**. This feeds your prep text to Whisper's `prompt` parameter, priming it to expect those words.

### 6. Calibrate
Two sections:

**Whisper Calibration** — Read 60 prompted sentences aloud. Builds personalized speech recognition data. Progress bar tracks completion. Each recording gets WER (Word Error Rate) feedback:
- Green = good match
- Yellow = OK
- Red = poor match

**Data Augmentation** — After calibration, generates 5× synthetic disfluent speech via TTS (word reps, phrase reps, interjections). Multiplies your training data.

**WER Trend** — Sparkline showing Word Error Rate across recent sessions. Lower = Whisper is getting better at understanding you.

### 7. Tips
Expandable categories of speech tips. Click a category header to expand. Each tip has a name, description, example, and source.

### 8. The File (Profile)
Your personal speech profile — everything the engine knows about you. Five collapsible sections:

| Section | What's in it | How to edit |
|---------|-------------|-------------|
| **Trigger Words** | Words you stutter on | Type + Enter or click + |
| **Filler Words** | Your personal fillers (um, uh, э) | Type + Enter or click + |
| **Vocabulary** | Preferred terms (names, jargon) | Type + Enter or click + |
| **Corrections** | Whisper mishearing → correct mapping | Fill both fields + Enter |
| **Covert Avoidance Pairs** | Auto-detected word substitution patterns | Read-only, engine-populated |

Click × on any tag to remove it.

---

## Compact Mode

Click `⊟` to collapse into a single horizontal bar showing:
- Brand name
- Status dot + state label
- Uptime
- Last output preview (truncated)
- Tags: Layer, Tone, Mode, Situation

Click `⊞` to expand back to full dashboard.

---

## Disconnected Screen

If the engine stops or loses connection (3+ failed polls), a full-screen overlay appears: **"CONNECTION LOST — Lavrentiy engine is not running"**. Restart the engine and it reconnects automatically.

---

## Bottom Bar

Footer with decorative hex screws and the disclaimer: *"Lavrentiy does his best. Check your shit before you send it."*

---

## Mobile PWA

On your phone: `http://192.168.1.65:7878/mobile`

Simplified interface — record button, result display, copy-to-clipboard. Runs the same pipeline (Whisper → filter → reconstruct). Add to home screen for standalone app feel.

---

## Keyboard Shortcuts (Default)

| Key | Action |
|-----|--------|
| F9 | Record / Stop |
| F10 | Cycle Tone |
| F11 | Cycle Layer |
| F12 | Print Stats |
| F3 ×3 | Quit Engine |
| Ctrl+Enter | Submit Prep text |
