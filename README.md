# LAVRENTIY

**Voice Reconstruction Engine** — *"We've got a file on you"*

Lavrentiy captures your voice, transcribes it via Whisper, reconstructs it through GPT-4o-mini, validates meaning with a secondary LLM pass (Falcon), and pastes the cleaned output directly into whatever app you were typing in. It learns your speech patterns over time — corrections, filler words, vocabulary, and stutter triggers — building a persistent profile that improves accuracy with every session.

## Architecture

Single Python process, ~68 KB total. No frameworks, no Electron, no build step.

```
Mic → Whisper → Reconstruction → Falcon Validation → Clipboard → Paste
```

- **Engine** (`lavrentiy.py`): Hotkey listener, audio capture, LLM pipeline, embedded HTTP server
- **Dashboard** (`dashboard.html`): Browser-based control panel served on `localhost:7878`
- **Profile** (`~/.lavrentiy/profile.json`): Persistent learned patterns and session history

## Layers

| Layer | Name | What it does |
|-------|------|-------------|
| 1 | Transcribe | Pure Whisper output, no LLM processing |
| 2 | Reconstruct | LLM cleans grammar, strips fillers, restructures |
| 3 | Profile | + your learned vocabulary, corrections, preferred terms |
| 4 | Stutter | + disfluency detection, trigger word tracking, insights |

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

## Auto-Learning

Every 3 sessions (Layer 2+), Lavrentiy analyzes your raw → output pairs and extracts:

- **Corrections**: Recurring Whisper misheard words (e.g., "Duncan" → "Dankeschön")
- **Fillers**: Filler sounds in any language (bilingual English/Russian support)
- **Vocabulary**: Domain-specific terms you consistently use
- **Triggers** (Layer 4): Words that cause disfluency patterns

New patterns land in **candidate buckets** first and must recur before promotion to the active profile. Corrections use a vote-based system — conflicting suggestions compete, and ties block promotion. This prevents single-occurrence hallucinations from poisoning the profile.

Profile data is normalized on ingestion and at startup: whitespace-trimmed, case-insensitively deduped, bounded by size caps.

## Risk Flags

Every pipeline run computes deterministic risk flags (no extra API calls):

| Flag | Trigger |
|------|---------|
| `validator_reject` | Falcon returned false |
| `reconstruct_fallback` | Reconstruction failed, raw text used |
| `very_short_output` | Suspiciously short clean output (Layer 2+) |
| `large_length_delta` | Clean/raw length ratio beyond threshold |
| `contains_unfinished_fragment` | Dangling connector or broken punctuation |

Flags are stored in the session decision object and shown as badges in the dashboard.

## Stutter Insights

At Layer 4, the dashboard's **Insights** tab surfaces deterministic observations from profile state — no extra API calls, no medical claims:

| Insight | Severity | Signal |
|---------|----------|--------|
| Recurring trigger words | High | 3+ trigger words accumulated |
| Heavy filler use | Medium | 5+ fillers above built-in baseline |
| Repeated misrecognitions | Medium | 5+ active corrections |
| New trigger words emerging | Medium | 3+ trigger detections in current session |
| Stable pattern week | Low | 10+ sessions, no concerns |

## Bilingual Support

Built for English/Russian bilingual speakers. Filler detection covers both languages. Cyrillic text in input triggers bilingual-aware reconstruction prompts.

## Dashboard

The dashboard is a single HTML file served by the engine's embedded HTTP server. It provides:

- Real-time state indicator (recording / processing / idle)
- Tone, layer, and mode controls
- Session stats and estimated API cost
- Live console log
- Learning event feed with progress tracking
- Stutter insights (Layer 4)
- Profile editor (triggers, fillers, vocabulary, corrections)

When the engine is not running, the dashboard shows a "CONNECTION LOST" overlay.

## Profile Safety

- **Atomic saves**: temp-write → fsync → rename (no partial writes)
- **Pre-migration backups**: timestamped snapshots in `~/.lavrentiy/backups/` before schema upgrades
- **Schema versioning**: current version 3 (vote-based candidate corrections, normalized data)

## Project Structure

```
lavrentiy.bat       # Windows launcher (pythonw, no console)
lavrentiy.py        # Engine + HTTP server (single process)
dashboard.html      # Browser UI (served by engine)
```

Runtime data stored at `~/.lavrentiy/`:
- `profile.json` — learned patterns, preferences, session history
- `dashboard.html` — served copy of the dashboard
- `backups/` — pre-migration profile snapshots
