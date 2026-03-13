# LAVRENTIY

**Voice Reconstruction Engine** — *"We've got a file on you"*

Lavrentiy captures your voice, transcribes it via Whisper, reconstructs it through GPT-4o-mini, validates meaning with a secondary LLM pass (Falcon), and pastes the cleaned output directly into whatever app you were typing in. It learns your speech patterns over time — corrections, filler words, vocabulary, and stutter triggers — building a persistent profile that improves accuracy with every session.

Built for people who stutter. The Layer 4 pipeline uses a clinically-informed reconstruction prompt grounded in stuttering research, covering overt disfluencies (part-word repetitions, prolongations, blocks, schwa substitution, consonant cluster breaks, tremors) and covert stuttering patterns (postponement fillers, synonym substitution, circumlocution, sentence abandonment, mazes/cluttering). Includes DAF (Delayed Auditory Feedback), covert avoidance detection, and a 5-feature phonetic risk model based on Brown's linguistic predictors of stuttering.

## Architecture

Single Python process, no frameworks, no Electron, no build step.

```
Mic → Whisper (stutter-aware prompt) → Disfluency Filter → Reconstruction (personalized phoneme context) → Falcon Validation → Clipboard → Paste
                                                                ↓
                                                    Covert Avoidance Detection ← Script Prep (intended text)
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
| 4 | Stutter | + disfluency detection, trigger word tracking, clinical insights, personalized onset weighting, per-user phoneme context in prompt, covert avoidance reversal |

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
| casual | 0.6x | Lighter cleanup — friends/family, low pressure |
| phone | 1.5x | Aggressive disfluency stripping — phone calls heavily exacerbate stuttering |
| presentation | 1.4x | Heavy cleanup, formal output — authority + audience + time pressure |
| interview | 1.6x | Maximum reconstruction aggressiveness — authority + judgment + time pressure |
| reading | 0.3x | Minimal cleanup — reading aloud is near-fluent for most PWS |

Situation is tracked per session in the history database and displayed as a tag on session cards in the dashboard.

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

At L1, this IS the output (no GPT call). At L2+, it pre-cleans input for GPT reconstruction. Post-filtering combined with decoder tuning yields significant WER reduction on disfluent speech (informed by Stutter-TTS and Mujtaba's "Inclusive ASR for Disfluent Speech" findings).

### Phonetic Risk Model (5 Features)

Predicts per-word stuttering risk using five linguistic features validated by FluencyBank research (Brown's predictors, confirmed in spontaneous speech):

| Feature | Source | Effect |
|---------|--------|--------|
| **Consonant onset** | Personalized onset weights learned from trigger history | /k/, /cr/, /p/ etc. scored per user, not population average |
| **Content vs function word** | `FUNCTION_WORDS` set | Function words get 0.1 floor; content words get 0.25+ base |
| **Sentence position** | Word index / sentence length | First 30% of sentence gets up to +0.15 boost (clause-boundary effect) |
| **Word length** | Character count | ≥7 chars: +0.10, ≥5 chars: +0.05 |
| **Word frequency** | `_HIGH_FREQ_WORDS` lookup (~1500 words, EN+RU) | Low-frequency words get +0.10 (rarer = harder to plan/produce) |

The same word scores differently depending on where it appears: "because" at sentence start (high risk) vs "...mostly because..." (lower risk). Feeds into Script Prep, exposure difficulty, trigger prediction, and the L4 reconstruction prompt.

### Personalized Onset Weighting

Analyzes trigger words to learn which phonetic onsets (e.g., /k/, /cr/, /p/) the user blocks on. Weights are personalized beyond population priors — dominant onsets get boosted (up to 0.9), unseen onsets get demoted (to 0.3). At Layer 4, the user's hardest phonemes are injected directly into the GPT reconstruction prompt: "Whisper output near these onsets is unreliable — trust semantic context over literal transcription."

## Covert Stuttering Detection

Tracks word-level avoidance patterns invisible to every other speech system. When a user pastes text into Script Prep ("I need to check the door") and then says something different ("I need to check the entrance"), Lavrentiy detects the substitution and checks whether the avoided word was phonetically risky.

**How it works:**

1. Script Prep buffers the intended text (5-minute expiry)
2. After transcription, `detect_covert_avoidance()` compares intended vs actual content words
3. Missing high-risk words (risk ≥ 0.5) with different-onset replacements at similar sentence positions are flagged as avoidance
4. Patterns stored in `covert_profile.avoidance_pairs[situation][word]` with avoided/used counts and common substitutes
5. At Layer 4, known avoidance pairs are injected into the reconstruction prompt — GPT is told to reconstruct with the intended word, not the avoidance substitute

**Example profile entry:**
```json
"covert_profile": {
  "avoidance_pairs": {
    "presentation": {
      "door": {
        "avoided_count": 12,
        "used_count": 3,
        "common_substitutes": ["entry", "front", "place"],
        "dominant_onset": "d"
      }
    }
  }
}
```

No other production speech app detects covert stuttering.

## Exposure Difficulty Scoring

Each utterance gets a 0.0–1.0 difficulty score based on:
- **Phonetic risk** (5-feature Brown model, weighted 0.35)
- **Situational pressure** (situation severity, weighted 0.25)
- **Disfluency density** (events per word, weighted 0.20)
- **Trigger word usage** (did you use known triggers?, weighted 0.20)

Bands: low (<0.2), moderate (0.2–0.4), high (0.4–0.6), very_high (>0.6). Logged per session. Enables therapy-aware tracking: "you used high-risk word X in 4/5 attempts this week."

## Editorial Distance Tracking

Normalized edit distance between raw transcription and final output, logged per session. As this number shrinks over time, the user is objectively producing more fluent speech — a concrete, data-backed sign of improvement.

## Redo Detection (Anti-Compulsion)

Tracks consecutive re-recordings of similar content within a time window. After 3+ redos, Lavrentiy prompts: "consider accepting this version and moving on." Prevents the re-recording loop.

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

Pre-speech word substitution (based on Ghai & Mueller, ASSETS '21). Paste upcoming text into the Prep tab — Lavrentiy flags high-risk words and suggests phonetically safer synonyms.

- **5-feature Brown risk scoring**: Every word scored with sentence context — onset, content/function, position, length, frequency. The same word scores differently at sentence start vs end.
- **Personalized onset weights**: Uses your learned onset weights — not generic population priors. Words starting with onsets you personally block on score higher.
- **Trigger word boosting**: Known trigger words from your profile score 1.0 (max risk). Words sharing onset patterns with triggers get a +0.2 boost.
- **LLM synonym generation**: Flagged words (risk ≥ 0.6) get 2–3 alternative words/phrases that preserve meaning but use easier onsets (vowels, continuants like /l/, /m/, /n/, /r/, /w/, /h/).
- **Swap-in-place**: Click any suggested alternative to replace the word directly in your script text.
- **Covert avoidance bridge**: Script Prep text is buffered as "intended content" for comparison against actual speech (see Covert Stuttering Detection).
- **Ctrl+Enter** shortcut to run analysis.

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
- Per-user hardest phonemes injected into L4 prompt with explicit guidance: "Whisper output near these onsets is unreliable"
- Known covert avoidance pairs injected into L4 prompt: if user avoids "door" → "entrance", GPT reconstructs with the intended word

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
- Script Prep with swap-in-place synonym replacement (Ctrl+Enter)
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
- **Schema versioning**: profile version 3 (vote-based candidate corrections, covert avoidance pairs)
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
