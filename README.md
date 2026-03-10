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
| 4 | Stutter | + disfluency detection and trigger word tracking |

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

All learned patterns persist in `profile.json` and feed into future reconstructions.

## Bilingual Support

Built for English/Russian bilingual speakers. Filler detection covers both languages. Cyrillic text in input triggers bilingual-aware reconstruction prompts.

## Dashboard

The dashboard is a single HTML file served by the engine's embedded HTTP server. It provides:

- Real-time state indicator (recording / processing / idle)
- Tone and layer controls
- Session stats and estimated API cost
- Live console log
- Learning event feed with progress tracking
- Profile editor (triggers, fillers, vocabulary, corrections)

When the engine is not running, the dashboard shows a "CONNECTION LOST" overlay.

## Project Structure

```
lavrentiy.bat       # Windows launcher (pythonw, no console)
lavrentiy.py        # Engine + HTTP server (single process)
dashboard.html      # Browser UI (served by engine)
```

Runtime data stored at `~/.lavrentiy/`:
- `profile.json` — learned patterns, preferences, session history
- `dashboard.html` — served copy of the dashboard
