# LAVRENTIY

**Voice Reconstruction Engine** — *"We've got a file on you"*

Lavrentiy captures your voice, transcribes it via Whisper, reconstructs it through GPT-4o-mini, validates meaning with a secondary LLM pass (Falcon), and pastes the cleaned output directly into whatever app you were typing in. It learns your speech patterns over time — corrections, filler words, vocabulary, and stutter triggers — building a persistent profile that improves accuracy with every session.

Built for people who stutter. The Layer 4 pipeline uses a clinically-informed reconstruction prompt grounded in research from the Stuttering Foundation, covering overt disfluencies (part-word repetitions, prolongations, blocks, schwa substitution, consonant cluster breaks, tremors) and covert stuttering patterns (postponement fillers, synonym substitution, circumlocution, sentence abandonment, mazes/cluttering). Includes DAF (Delayed Auditory Feedback) for real-time fluency training.

## Architecture

Single Python process, no frameworks, no Electron, no build step.

```
Mic → Whisper → Reconstruction → Falcon Validation → Clipboard → Paste
```

- **Engine** (`lavrentiy.py`): Hotkey listener, audio capture, LLM pipeline, DAF streaming, embedded HTTP server
- **Dashboard** (`dashboard.html`): Browser-based control panel served on `localhost:7878`
- **Profile** (`~/.lavrentiy/profile.json`): Persistent learned patterns and preferences
- **History** (`~/.lavrentiy/history.db`): SQLite session database (WAL mode, unlimited history)

## Layers

| Layer | Name | What it does |
|-------|------|-------------|
| 1 | Transcribe | Pure Whisper output, no LLM processing |
| 2 | Reconstruct | LLM cleans grammar, strips fillers, restructures |
| 3 | Profile | + your learned vocabulary, corrections, preferred terms |
| 4 | Stutter | + disfluency detection, trigger word tracking, clinical insights |

## Modes

| Mode | Behavior |
|------|----------|
| **RAW** | Paste raw transcription, no reconstruction |
| **FAST** | Reconstruct but skip Falcon validation (~500ms faster) |
| **SAFE** | Full pipeline with Falcon meaning check (default) |

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

**Phonetic trigger awareness**:
- Stop plosives (/p/, /b/, /t/, /d/, /k/, /g/) and affricates (/tʃ/, /dʒ/)
- Consonant-vowel transitions and consonant clusters
- Initial word/clause boundary positions

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
- Tone, layer, and mode controls
- DAF toggle and delay slider
- Session stats and estimated API cost
- Live console log
- Session history (SQLite-backed, unlimited)
- Learning event feed with progress tracking
- Clinical stutter insights with therapeutic techniques (Layer 4)
- Stuttering Foundation tips reference (56 entries, 8 categories)
- Profile editor (triggers, fillers, vocabulary, corrections)

## Data Safety

- **Atomic profile saves**: temp-write → fsync → rename (no partial writes)
- **SQLite WAL mode**: concurrent reads during writes, no corruption
- **Pre-migration backups**: timestamped snapshots in `~/.lavrentiy/backups/`
- **Schema versioning**: profile version 3 (vote-based candidate corrections)

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
