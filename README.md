# LAVRENTIY

**Voice Reconstruction Engine** — *"We've got a file on you"*

Lavrentiy captures your voice, transcribes it via Whisper, reconstructs it through GPT-4o-mini, validates meaning with a secondary LLM pass (Falcon), and pastes the cleaned output directly into whatever app you were typing in. It learns your speech patterns over time — corrections, filler words, vocabulary, and stutter triggers — building a persistent profile that improves accuracy with every session.

Built for people who stutter. The Layer 4 pipeline uses a clinically-informed reconstruction prompt grounded in research from the Stuttering Foundation, covering overt disfluencies (part-word repetitions, prolongations, blocks, schwa substitution, consonant cluster breaks, tremors) and covert stuttering patterns (postponement fillers, synonym substitution, circumlocution, sentence abandonment, mazes/cluttering). Includes DAF (Delayed Auditory Feedback) for real-time fluency training.

## Architecture

Single Python process, no frameworks, no Electron, no build step.

```
Mic → Whisper (stutter-aware prompt) → Disfluency Filter → Reconstruction → Falcon Validation → Clipboard → Paste
```

- **Engine** (`lavrentiy.py`): Hotkey listener, audio capture, LLM pipeline, DAF streaming, calibration, augmentation, embedded HTTP server
- **Dashboard** (`dashboard.html`): Browser-based control panel served on `localhost:7878`
- **Profile** (`~/.lavrentiy/profile.json`): Persistent learned patterns and preferences
- **History** (`~/.lavrentiy/history.db`): SQLite session database (WAL mode, unlimited history)
- **Calibration** (`~/.lavrentiy/calibration/`): 60-prompt structured data collection with WER tracking
- **Audio Archive** (`~/.lavrentiy/audio_archive/`): Session WAV + metadata pairs for future Whisper fine-tuning
- **Augmented Data** (`~/.lavrentiy/calibration/augmented/`): Synthetic disfluent speech via TTS for dataset multiplication

## Layers

| Layer | Name | What it does |
|-------|------|-------------|
| 1 | Transcribe | Whisper output + disfluency post-filter (strips repetitions, fillers) |
| 2 | Reconstruct | LLM cleans grammar, strips fillers, restructures |
| 3 | Profile | + your learned vocabulary, corrections, preferred terms |
| 4 | Stutter | + disfluency detection, trigger word tracking, clinical insights, personalized onset weighting |

## Modes

| Mode | Behavior |
|------|----------|
| **RAW** | Paste raw transcription, no reconstruction |
| **FAST** | Reconstruct but skip Falcon validation (~500ms faster) |
| **SAFE** | Full pipeline with Falcon meaning check (default) |

## Situational Context

| Situation | Severity | Effect |
|-----------|----------|--------|
| default | 1.0x | Standard reconstruction |
| casual | 0.8x | Lighter cleanup |
| phone | 1.2x | More aggressive disfluency stripping |
| presentation | 1.4x | Heavy cleanup, formal output |
| interview | 1.6x | Maximum reconstruction aggressiveness |
| reading | 0.9x | Preserve structure of read text |

## Tones

`casual` · `professional` · `friend` · `formal`

## Hotkeys

| Key | Action |
|-----|--------|
| **F9** (hold) | Record while held, process on release |
| **F10** | Cycle tone |
| **F11** | Cycle layer |
| **F12** | Print stats to console |
| **F3 × 3** | Quit (triple-tap within 0.8s) |

## Setup

### Requirements

- Python 3.10+
- Windows (uses Win32 APIs for focus management and single-instance mutex)
- `OPENAI_API_KEY` environment variable

### Install dependencies

```
pip install openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy
```

### Run

```
lavrentiy.bat
```

Or directly:
```
pythonw lavrentiy.py
```

Dashboard opens at [http://localhost:7878](http://localhost:7878)

## Pipeline Detail

### Whisper (Stutter-Aware)

The Whisper API call includes a decoder-biasing prompt that steers transcription toward intended speech rather than faithful disfluency reproduction. Research shows decoder tuning alone can reduce WER by 51.2% on stuttered speech.

### Disfluency Post-Filter

Zero-cost rule-based cleanup applied after Whisper, before GPT reconstruction:

- **Stutter fragments**: `"p- p- pop"` → `"pop"`
- **Word repetitions**: `"I I I want"` → `"I want"`
- **Phrase repetitions**: `"I want I want to go"` → `"I want to go"`
- **Filler stripping**: removes `um`, `uh`, `er`, `ah` + Russian equivalents (`э`, `ээ`, `ну`)

At L1, this IS the output (no GPT call). At L2+, it pre-cleans input for GPT reconstruction. Research shows post-filtering reduces WER by 28.7%; combined with decoder tuning: 61.2%.

### Personalized Phonetic Onset Weighting

Analyzes trigger words to learn which phonetic onsets (e.g., /k/, /cr/, /p/) the user blocks on. Weights are personalized beyond population priors — dominant onsets get boosted (up to 0.9), unseen onsets get demoted (to 0.3). Feeds into `predict_phonetic_risk()` for Script Prep and clinical insights.

## Calibration Mode

Structured 60-prompt data collection across 12 categories:

| Category | Focus |
|----------|-------|
| Smart Home | Short commands |
| Healthcare | Clinical terms |
| Finance | Numbers, proper nouns |
| Navigation | Place names, directions |
| Communication | Emails, calls, messages |
| Shopping | E-commerce |
| Productivity | Calendar, meetings |
| Media | Entertainment |
| Phonetic Challenge | Loaded with /p/, /k/, /cr/ trigger onsets |
| Spontaneous | Job-interview format, natural speech |
| Technical | Code-switching, technical terms |
| Personal | Real names (Jana, Alex), family context |

Each recording runs through Whisper with WER computed against ground truth. Data feeds future LoRA fine-tuning.

## Data Augmentation

Synthetic disfluent speech generation (based on Mujtaba24 Interspeech methodology):

1. Takes completed calibration prompts
2. Injects text-level disfluencies: word repetitions (1-6x), phrase repetitions (1-5x), interjection insertions (1-7x)
3. Synthesizes via OpenAI TTS with rotating voices and speed variation (0.85-1.15x)
4. Runs each through Whisper to capture ASR behavior
5. Saves WAV + metadata JSON with WER

60 real samples × 4 variants = 240 synthetic training pairs. Total dataset: 300 samples.

## Script Prep

Pre-speech word substitution (based on Ghai & Mueller, ASSETS '21). Paste upcoming text into the Prep tab — Lavrentiy flags high-risk words based on phonetic onset analysis and your personal trigger history, and suggests safer synonyms.

## DAF (Delayed Auditory Feedback)

Plays your mic audio back through headphones with a configurable delay (30–300ms, default 100ms). The delayed echo creates a choral reading effect that reduces stuttering blocks for many speakers. Toggle on/off and adjust the delay slider in the dashboard sidebar. Uses the same mic device as the recording pipeline. No extra dependencies — built on `sounddevice` streaming.

## Auto-Learning

Every 3 sessions (Layer 2+), Lavrentiy analyzes your raw → output pairs and extracts:

- **Corrections**: Recurring Whisper misheard words (e.g., "Duncan" → "Dankeschön")
- **Fillers**: Filler sounds in any language (bilingual English/Russian support)
- **Vocabulary**: Domain-specific terms you consistently use
- **Triggers** (Layer 4): Words that cause disfluency patterns

New patterns land in **candidate buckets** first and must recur before promotion to the active profile. Corrections use a vote-based system — conflicting suggestions compete, and ties block promotion. This prevents single-occurrence hallucinations from poisoning the profile.

## Layer 4: Clinical Stuttering Support

The Layer 4 reconstruction prompt is informed by clinical research from the Stuttering Foundation:

**Overt disfluencies** (strip and reconstruct):
- Part-word repetitions, whole-word repetitions, prolongations
- Schwa vowel substitution in repeated syllables
- Consonant cluster breaks (failed blends inject schwa)
- Blocks (silent fixations), tremors, secondary behaviors

**Covert stuttering** (recognize as avoidance, not content):
- Postponement fillers / starters
- Word substitution and circumlocution
- Sentence abandonment, covert interruption
- Mazes / cluttering (rambling run-on filler)

**Whisper ASR failure modes on stuttered speech** (in L4 prompt):
- Hallucination during blocks (invents words from silence)
- Syllable deletion (collapses repeated syllables)
- Phantom word insertion
- Schwa corruption in repetitions
- Pause hallucination (inserts punctuation/filler words)
- Word boundary errors at repetition junctions
- Partial word ghosts

**Phonetic trigger awareness**:
- Stop plosives (/p/, /b/, /t/, /d/, /k/, /g/) and affricates (/tʃ/, /dʒ/)
- Consonant-vowel transitions and consonant clusters
- Initial word/clause boundary positions
- Personalized dominant onset patterns (learned from user's trigger history)

**Clinical insights** (Insights tab, Layer 4):
Each insight prescribes specific therapeutic techniques — Preparatory Sets, Voluntary Stuttering, Pull-Outs, Easy Onset, Coarticulation Practice — sourced from Stuttering Foundation publications.

**Tips reference** (Tips tab):
56 clinical entries across 8 categories with source document citations: Trigger Patterns, Situational Modifiers, Avoidance Behaviors, Disfluency Types, Therapeutic Techniques, Persistent vs. Developmental Markers, Cognitive/Emotional Patterns, and Hard Statistics.

## Risk Flags

Every pipeline run computes deterministic risk flags (no extra API calls):

| Flag | Trigger |
|------|---------|
| `validator_reject` | Falcon returned false |
| `reconstruct_fallback` | Reconstruction failed, raw text used |
| `very_short_output` | Suspiciously short clean output (Layer 2+) |
| `large_length_delta` | Clean/raw length ratio beyond threshold |
| `contains_unfinished_fragment` | Dangling connector or broken punctuation |

## Bilingual Support

Built for English/Russian bilingual speakers. Filler detection covers both languages. Cyrillic text in input triggers bilingual-aware reconstruction prompts.

## Dashboard

Single HTML file served by the engine's embedded HTTP server:

- Real-time state indicator (recording / processing / idle)
- Tone, layer, mode, and situation controls
- DAF toggle and delay slider
- Session stats and estimated API cost
- Live console log
- Session history (SQLite-backed, unlimited)
- Learning event feed with progress tracking
- Clinical stutter insights with therapeutic techniques (Layer 4)
- Script Prep (pre-speech word risk analysis)
- Calibration mode (60 prompts, WER tracking, progress bar)
- Data augmentation controls (synthetic disfluent speech generation)
- Stuttering Foundation tips reference (56 entries, 8 categories)
- Profile editor (triggers, fillers, vocabulary, corrections)
- Compact mode (minimized bar for always-on-top use)
- Customizable hotkeys

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | Engine state, tone, layer, mode, situation, stats |
| GET | `/api/profile` | Full profile data |
| GET | `/api/sessions` | Last 50 sessions |
| GET | `/api/log` | Console log |
| GET | `/api/learn` | Learning status, events, onset weights, insights |
| GET | `/api/wer` | WER stats from session history |
| GET | `/api/archive` | Archive stats (sessions, size, fine-tuning readiness) |
| GET | `/api/calibration` | Calibration progress + next prompt |
| GET | `/api/augment` | Augmentation status |
| POST | `/api/tone` | Set tone |
| POST | `/api/layer` | Set layer |
| POST | `/api/mode` | Set mode |
| POST | `/api/situation` | Set situational context |
| POST | `/api/profile` | Update profile sections |
| POST | `/api/prep` | Script Prep analysis |
| POST | `/api/daf` | DAF toggle/delay |
| POST | `/api/calibration/start` | Begin calibration session |
| POST | `/api/calibration/record` | Submit calibration recording (base64 WAV) |
| POST | `/api/calibration/skip` | Skip a prompt |
| POST | `/api/calibration/stop` | End calibration session |
| POST | `/api/augment` | Trigger augmentation generation |

## Data Safety

- **Atomic profile saves**: temp-write → fsync → rename (no partial writes)
- **SQLite WAL mode**: concurrent reads during writes, no corruption
- **Pre-migration backups**: timestamped snapshots in `~/.lavrentiy/backups/`
- **Schema versioning**: profile version 3 (vote-based candidate corrections)
- **All data local**: everything stored in `~/.lavrentiy/`, nothing server-side except OpenAI API calls
- **Archive budget**: auto-pause at 2GB to prevent disk fill

## Project Structure

```
lavrentiy.bat       # Windows launcher (pythonw, no console)
lavrentiy.py        # Engine + HTTP server (single process)
dashboard.html      # Browser UI (served by engine)
```

Runtime data at `~/.lavrentiy/`:
- `profile.json` — learned patterns and preferences
- `history.db` — SQLite session database
- `dashboard.html` — served copy of the dashboard
- `backups/` — pre-migration profile snapshots
- `calibration/` — calibration WAV + metadata pairs
- `calibration/augmented/` — synthetic disfluent training data
- `audio_archive/` — session WAV + metadata pairs for fine-tuning
