# LAVRENTIY

**Voice Reconstruction Engine**

Lavrentiy captures voice via microphone, transcribes with Whisper (with optional decoder seeding, block preservation, confidence targeting, and multi-temperature voting), reconstructs through GPT-4o/4o-mini with personalized phoneme context, validates meaning with Falcon, and pastes output into the active application. It learns speech patterns over time — corrections, filler words, vocabulary, and stutter triggers — building a persistent profile.

Built for people who stutter. The Layer 4 pipeline uses a reconstruction prompt informed by stuttering research, covering overt disfluencies (part-word repetitions, prolongations, blocks, schwa substitution, consonant cluster breaks) and covert stuttering patterns (postponement fillers, synonym substitution, circumlocution, sentence abandonment). Includes DAF (Delayed Auditory Feedback), covert avoidance detection, and a 5-feature phonetic risk model based on Brown's linguistic predictors.

## Architecture

Single Python process, no frameworks, no Electron, no build step.

```
                    Script Prep (intended text)
                        ↓ (decoder seeding)
Mic → Whisper (Script Prep seed | verbose JSON | multi-temp voting)
        ↓                                  ↓
   Disfluency Filter              Low-confidence segments
        ↓                          + disagreement map
   Paralinguistic Detection ←── HNR + error patterns (±1s rule)
        ↓
   Reconstruction (phoneme context + Whisper confidence + paralinguistic events)
        ↓
   Falcon Validation → Clipboard → Paste
        ↓
   Covert Avoidance Detection ← Script Prep
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
| 1 | Transcribe | Enhanced Whisper (Script Prep seeding, block preservation, verbose JSON) + disfluency post-filter |
| 2 | Reconstruct | LLM cleans grammar, strips fillers, restructures (generic — no personal data) |
| 3 | Profile | + your learned vocabulary, corrections, preferred terms (vocabulary/corrections injected at L3+, not L2) |
| 4 | Stutter | + disfluency detection, trigger word tracking, clinical insights, personalized onset weighting, per-user phoneme context in prompt, covert avoidance reversal |
| 5 | Paralinguistic | + non-verbal event detection (laughter, cough, sigh, breathing, throat-clearing, pauses) via HNR analysis + Whisper error patterns. Detected events injected into reconstruction prompt to prevent hallucination near non-speech audio. + Prosodic bridging: per-segment F0/energy/rate extraction, speaker state inference, stutter-specific prosodic rules. Rich acoustic context injected into GPT prompt to recover information Whisper's text decoder destroys |

## Modes

| Mode | Behavior |
|------|----------|
| **RAW** | Paste raw transcription, no reconstruction |
| **FAST** | Reconstruct but skip Falcon validation (~500ms faster) |
| **SAFE** | Full pipeline with Falcon meaning check (default) |

## Situational Context

| Situation | Severity | Effect |
|-----------|----------|--------|
| Default | 1.0x | Standard reconstruction — everyday use |
| High Stress | 1.5x | Auto-L4 + DAF + all toggles ON — full assist for phone, presentation, interview |
| Reading | 0.3x | Light touch — reading aloud is near-fluent for most PWS |

Collapsed from 6 situations to 3 (phone/presentation/interview merged into High Stress, casual merged into Default). Old situation names (`phone`, `interview`, `presentation`, `casual`) still work via back-compat aliases. Situation is tracked per session in the history database and displayed as a tag on session cards in the dashboard.

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

### Whisper (Enhanced Stutter Pipeline)

The Whisper integration goes beyond a simple API call. Four parameter-level optimizations work together:

**1. Script Prep Decoder Seeding**
When Script Prep text is available (user typed what they intend to say), it's passed as Whisper's `prompt` parameter — the decoder conditioning token. Whisper's beam search treats this as "previously transcribed text." This reduces hallucination on blocked or disfluent segments. Falls back to a fluency-biasing prompt when no Script Prep exists.

**2. Block Detection (via `no_speech_prob`)**
Verbose JSON returns per-segment `no_speech_prob` — how close Whisper came to classifying a segment as silence. The OpenAI API applies its own internal threshold server-side (~0.6), but segments that survive with high `no_speech_prob` are flagged as "block suspects" — Whisper hallucinated filler text into what was really strained silence (a block). These are flagged in the L4 prompt: "discard these words entirely or replace with the word the speaker was trying to say."

**3. Confidence Targeting (`avg_logprob`)**
Verbose JSON mode returns per-segment `avg_logprob` confidence scores. Low-confidence segments near Brown high-risk positions (consonant-initial content words early in sentence) are flagged and injected into the L4 reconstruction prompt as "Whisper is uncertain here — reconstruct aggressively."

**4. Multi-Temperature Voting**
Three Whisper calls at temperatures 0, 0.2, and 0.4. Where all three agree = confident. Where they disagree = the audio is ambiguous = almost certainly a disfluency artifact. Disagreements are word-level aligned and passed to L4 as precision-targeted reconstruction hints. Configurable via `/api/whisper_config`.

These four enhancements are designed to stack. Actual WER improvement depends on the speaker and context.

### Disfluency Post-Filter

Zero-cost rule-based cleanup applied after Whisper, before GPT reconstruction:

- **Stutter fragments**: `"p- p- pop"` → `"pop"`
- **Word repetitions**: `"I I I want"` → `"I want"`
- **Phrase repetitions**: `"I want I want to go"` → `"I want to go"`
- **Filler stripping**: removes `um`, `uh`, `er`, `ah` + Russian equivalents (`э`, `ээ`, `ну`)

At L1, this IS the output (no GPT call). At L2+, it pre-cleans input for GPT reconstruction. Post-filtering approach informed by Stutter-TTS and Mujtaba's "Inclusive ASR for Disfluent Speech" findings.

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

**Verified against original research:** All four of Brown's factors have been verified factor-by-factor against the 1945 paper with page citations. See **[docs/browns_verification.md](docs/browns_verification.md)** for the full verification including Table 4/5/6 data and code comparison.

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

Covert stuttering detection is not commonly implemented in consumer speech tools.

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
- **Whisper decoder seeding**: Script Prep text is also fed as Whisper's `prompt` parameter — the decoder conditioning token, which biases Whisper toward the expected vocabulary.
- **Ctrl+Enter** shortcut to run analysis.

## Clipboard Predictor

Background daemon thread that pre-builds Whisper `initial_prompt` bias from clipboard content. Zero-blocking — the bias is always pre-computed and cached before you press record.

**How it works:**
1. Polls clipboard every 4 seconds
2. Scores all words locally via `compute_brown_scores()` (instant, no API call)
3. If ≥2 words exceed 0.55 risk AND situation is high-pressure (high_stress) → fires an async LLM call for fluency-friendly synonyms
4. Caches the result as Whisper `initial_prompt` bias (5-minute TTL)
5. When you record, `_build_whisper_prompt()` checks the cache — if bias exists, Whisper gets it for free

**Priority chain:** Script Prep (explicit) > Clipboard Predictor (passive) > generic fluency prompt (fallback).

The LLM prompt uses your personal onset weights to ask for synonyms starting with continuants (/l/, /m/, /n/, /r/, /w/, /h/) or vowels. Cache invalidates automatically on situation change.

## Live Trigger Warning

Real-time risk visualization in the live preview bar. As Whisper streams interim results, each word is scored via `predict_phonetic_risk()` and color-coded:

- **Risk ≥ 0.8**: Red with pulsing animation — high block probability
- **Risk ≥ 0.6**: Yellow with wavy underline — moderate risk
- **Below 0.6**: Normal text

Known trigger words from the profile are forced to 1.0 (always red). Gives the speaker a visual heads-up on upcoming difficult words before they finish the utterance.

## Situation Pre-Warm

When you switch situations, Lavrentiy auto-configures the full stack:

| Situation | DAF | Layer | Toggles | Prep Text |
|-----------|-----|-------|---------|-----------|
| High Stress | 100ms | L4 | Paralinguistic ON, Prosodic ON | "Hello this is speaking. Thank you for having me. Next slide." |
| Reading | Off | L3 | (unchanged) | (none) |

Prep text is loaded automatically as Script Prep, which means Whisper decoder seeding is instant — you don't have to type anything. Clipboard predictor cache also invalidates on situation change for immediate re-scoring.

## Shadow Utterance

"What you probably meant to say." For prepped text, the Script Prep IS the shadow (zero cost). For unprepped text, one LLM call infers intended speech from the partial/disfluent context. The diff between shadow and actual transcript = **avoidance drift score** — a quantitative measure of how far the spoken output deviated from intent. History tracked per session.

## Weekly Clinical Report

Aggregates session analytics in Python and sends structured data to GPT-4o-mini for a therapist-grade narrative summary. Metrics included:

- Edit distance trend (first half vs second half of period — improving or regressing?)
- Pause ratio averages
- Top onset triggers by frequency
- Situation breakdown (which contexts produce the most disfluency)
- Language breakdown (EN vs RU)
- Covert avoidance event counts
- Correction and trigger counts

Output is a clinical summary suitable for sharing with an SLP. Available via the 📊 button in the Learning tab.

## Fluency Trend Tracking

Per-session fluency scores (0.0–1.0) computed from disfluency density, edit distance, and speaking rate. Persisted in SQLite. The `/api/fluency` endpoint returns the full trend array plus a moving average, enabling the dashboard to render a fluency sparkline over time. Severity decomposition breaks the score into component factors.

## Speech Rate Analysis

Syllable-per-second speaking rate estimated from word count and audio duration. Tracked per session. Abnormally slow rate (< 2.0 syl/s) may indicate prolongations or blocks not captured by Whisper.

## Substitution Fingerprinting

Tracks onset-level substitution patterns across sessions. If a speaker consistently replaces /k/-initial words with /m/-initial synonyms, the fingerprint captures this as a directional avoidance vector. Used to predict future avoidance before it happens.

## Profile Decay

Stale profile entries (trigger words, fillers, corrections) that haven't been reinforced by recent sessions gradually lose weight. Prevents the profile from accumulating false positives from early sessions when calibration data was sparse. Runs automatically every 5 sessions.

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

## Layer 5: Paralinguistic Event Detection

Detects non-verbal paralinguistic events (laughter, cough, sigh, breathing, throat-clearing, pauses) using audio analysis and Whisper's own errors as detection signals. No ML model required — pure signal processing + error pattern analysis.

**Key insight (Zhang, 2024):** 96.1% of ASR errors cluster within ±1 second of a paralinguistic event boundary. Whisper's errors are the detector.

**Detection pipeline:**

1. **Error-type classifier**: WER S/D/I backtrace → event hypothesis (S+D cluster = laughter, insertions = sigh/throat-clearing)
2. **No-speech probability**: High `no_speech_prob` segments → breathing/pause candidates
3. **Disagreement clusters**: Dense multi-temp voting disagreements → non-speech audio
4. **HNR confirmation**: Extract ±1s audio window around candidate → compute Harmonics-to-Noise Ratio. HNR < 4.0 dB confirms paralinguistic event (speech averages ~12 dB, coughs ~-15 dB)
5. **Temporal gating**: Discard events < 500ms; laughter requires 1000ms sustained evidence

**Phase 1 tags:** `[Laughter]`, `[Cough]`, `[Sigh]`, `[Pause]`, `[Throat-clearing]`, `[Breathing]`

**Prompt injection:** At Layer 5, detected events are injected into the reconstruction prompt: "Whisper was confused near [Laughter] at 3.2s–4.1s — ignore hallucinated text in this window." This prevents the LLM from trying to interpret non-speech audio as garbled words.

## Layer 5.5: Prosodic Bridging

Recovers acoustic features that Whisper's text decoder destroys and describes them as structured text for GPT. Validated by two papers: USDM (Kim et al., NeurIPS 2024) proved acoustic tokens preserve prosodic info through tokenization; SpeechEmotionLlama (Kang et al., Interspeech 2025, MIT/Meta) proved frozen LLMs respond to text-described paralinguistic state.

**Per-segment features:**
- **F0 (pitch)**: autocorrelation peak frequency, same infrastructure as `compute_hnr()`
- **F0 variance**: pitch stability across sub-windows within each segment
- **Pitch direction**: rising / falling / flat / erratic (from F0 contour slope)
- **RMS energy**: segment loudness
- **Speaking rate**: syllables per second per segment

**Speaker baseline:** Running averages of F0/energy/rate from historical sessions, stored in `profile.json` under `prosodic_baseline`. Current session features compared in sigma units.

**Speaker state inference:** Maps prosodic deviations to natural language descriptions:
- High F0 variance + fast rate + high energy → "Elevated stress/arousal"
- Dropping energy + slow rate → "Low energy/fatigue"
- Erratic F0 → "Vocal tension"
- Near baseline → "Calm/casual"

**Stutter-specific prosodic rules:**
| Acoustic Pattern | Interpretation | Reconstruction |
|---|---|---|
| Block + laughter context | Self-deprecating humor | Reconstruct lightly, preserve tone |
| Block + dropping energy | Frustration/shutdown | Reconstruct gently |
| Repetition + rising pitch | Genuine struggle | Aggressive reconstruction |
| Repetition + stable pitch | Emphatic repetition, NOT stutter | Leave it |
| Filler + flat energy + constant pitch | Postponement stalling | Strip it |
| Filler + rising pitch | Discourse marker ("you know?") | Keep it |

**Automatic situation inference:** If F0/energy/rate exceed 1.5σ above baseline, logs a suggestion that the situation may warrant upgrade. Does not auto-switch — George can override.

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

- Real-time state indicator (recording / processing / idle) with clickable timer reset
- Hardware boot-up sequence animation on load (panels fade in, numbers count up)
- Tone, layer, mode, and situation controls with inline descriptions
- Layer-aware UI: Tone and Mode sections collapse when on Layer 1 (Transcribe) with "select Reconstruct +" hint
- Paralinguistic toggle with Transcribe sub-toggle (inject [tags] in text) — L-connector visual
- Prosodic toggle — auto-enables on Layer 4 (Stutter)
- DAF toggle and delay slider
- Live preview bar with risk-colored trigger warnings
- Session stats (words, sessions, API calls, cost) with clickable stat cards
- Live console log (color-coded: white=speech, green=status, yellow=analytics, red=prosodic alerts, brown=block suspects)
- Session history with transparent hover-to-opaque cards, exposure bands, edit distance
- Learning event feed with solid tag badges (TRIGGER, CAND, VOCAB, FILLER)
- Clinical stutter insights with transparent card treatment (Layer 4)
- Script Prep with swap-in-place synonym replacement (Ctrl+Enter)
- Weekly clinical report generation
- Calibration mode (60 prompts, WER tracking, WER trend chart)
- Data augmentation controls (synthetic disfluent speech generation)
- Stuttering Foundation tips reference (56 entries, 8 categories)
- Profile editor (triggers, fillers, vocabulary, corrections, covert pairs management)
- Compact mode (minimized always-on-top bar with essential controls)
- Customizable hotkeys (F1–F12 rebinding via sidebar editor)
- Interactive help manual (accordion-style, searchable, matching dashboard aesthetic)
- Situations collapsed to 3 (Default, High Stress, Reading) from original 6

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | Engine state, tone, layer, mode, situation, stats |
| GET | `/api/profile` | Full profile data |
| GET | `/api/sessions` | Last 50 sessions |
| GET | `/api/log` | Console log |
| GET | `/api/learn` | Learning status, events, onset weights, insights |
| GET | `/api/wer` | WER stats from session history |
| GET | `/api/fluency` | Fluency trend array + moving average |
| GET | `/api/preview` | Live preview text with per-word risk scores |
| GET | `/api/archive` | Archive stats (sessions, size, fine-tuning readiness) |
| GET | `/api/calibration` | Calibration progress + next prompt |
| GET | `/api/augment` | Augmentation status |
| GET | `/api/severity` | Current severity decomposition |
| GET | `/api/hotkeys` | Current hotkey bindings |
| GET | `/api/daf` | DAF state and delay |
| POST | `/api/tone` | Set tone |
| POST | `/api/layer` | Set layer |
| POST | `/api/mode` | Set mode |
| POST | `/api/situation` | Set situational context (triggers pre-warm) |
| POST | `/api/profile` | Update profile sections |
| POST | `/api/prep` | Script Prep analysis |
| POST | `/api/daf` | DAF toggle/delay |
| POST | `/api/hotkeys` | Update hotkey bindings (F1–F12) |
| GET  | `/api/report` | Generate weekly clinical report (GPT-4o-mini) |
| POST | `/api/whisper_config` | Whisper params: `no_speech_threshold`, `multi_temp` toggle |
| POST | `/api/whisper_temp` | Set Whisper decoder temperature |
| POST | `/api/covert/remove` | Remove a covert avoidance pair |
| POST | `/api/calibration/start` | Begin calibration session |
| POST | `/api/calibration/record` | Submit calibration recording (base64 WAV) |
| POST | `/api/calibration/skip` | Skip a prompt |
| POST | `/api/calibration/stop` | End calibration session |
| POST | `/api/augment` | Trigger augmentation generation |
| GET  | `/api/calibration/prompts` | List all calibration prompts |
| POST | `/api/paralinguistic` | Toggle paralinguistic detection |
| POST | `/api/paralinguistic_transcribe` | Toggle tag injection into pasted text |
| POST | `/api/prosodic` | Toggle prosodic analysis |
| POST | `/api/transcribe` | Mobile transcription endpoint (base64 WAV in, text out) |

## Data Safety

- **Atomic profile saves**: temp-write → fsync → rename (no partial writes)
- **SQLite WAL mode**: concurrent reads during writes, no corruption
- **Pre-migration backups**: timestamped snapshots in `~/.lavrentiy/backups/`
- **Schema versioning**: profile version 4 (vote-based candidate corrections, covert avoidance pairs, phonetic triggers, OCD speech profile)
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

## Brown's Paper Verification (2026-03-15)

The 5-feature phonetic risk model was verified against the original 1945 paper: Spencer F. Brown, "The Loci of Stutterings in the Speech Sequence," *Journal of Speech Disorders*, Vol. 10, No. 3, pp. 181–192. All four original factors are correctly implemented. The 5th feature (word frequency) is properly attributed to FluencyBank 2023. Full verification with page citations, table data, and factor-by-factor comparison: **[docs/browns_verification.md](docs/browns_verification.md)**

Key finding from Brown: rank-order correlation between factor count and stuttering frequency was **.99 ± .003** (Table 4, p. 186). Only 5.3% of 5,136 stutterings could not be accounted for by at least one factor.

## Test Coverage — Updated 2026-03-21

**1034 assertions passing across 14 test suites.**

| Suite | Assertions | Coverage |
|-------|-----------|----------|
| `test_core.py` | 39 | `_extract_onset`, `learn_onset_weights`, `predict_phonetic_risk`, `SITUATION_SEVERITY` (3 situations), `compute_wer`, `compute_risk_flags`, `make_decision` |
| `test_clinical.py` | 94 | `compute_exposure_difficulty`, `compute_editorial_distance`, `detect_covert_avoidance`, `compute_substitution_fingerprint`, `check_redo`, `track_profile_relevance`, `decay_stale_profile_entries`, `update_covert_profile` |
| `test_integration.py` | 53 | `strip_disfluencies`, `count_disfluencies`, `detect_ocd_loops`, database round-trip, profile schema migration, bilingual filler detection |
| `test_pending.py` | 127 | `detect_word_language`, `detect_onset_anomalies`, `compute_brown_scores`, `predict_triggers_in_text`, `generate_shadow_utterance`, `compute_avoidance_trend`, `_build_whisper_prompt`, `learn_from_sessions`, `build_stutter_insights` |
| `test_pipeline.py` | 96 | Pipeline stage chaining, L1/L2/L4 data flow, mode×layer decision matrix, critical token retention, disfluency→exposure→editorial chain, trigger detection chain, profile corrections, situation severity ordering (high_stress > default > reading) |
| `test_endpoints.py` | 170 | All GET/POST HTTP endpoints, JSON response shape, state mutations, CORS headers, error handling, `/api/covert/remove` edge cases, DAF endpoints, calibration flow, augmentation flow, paralinguistic/prosodic toggle endpoints, paralinguistic_transcribe toggle, situation alias back-compat (phone→high_stress, casual→default), toggle auto-enable on high-stress |
| `test_threads.py` | 22 | Concurrent `_shadow_history` writes, trend reads during writes, `stats_inc` atomicity, `preview_state` updates, `learn_events` writes + snapshots, onset anomaly detection |
| `test_fuzz.py` | 23 | 36,000+ random inputs (ASCII, Unicode, CJK, emoji, null bytes, massive) across 12 functions — invariant verification: scores in [0,1], no crashes, valid return types |
| `test_perf.py` | 18 | Timing thresholds for 12 functions — prevents silent slowdowns (e.g. `predict_phonetic_risk` < 1ms, `strip_disfluencies` 7.4KB < 100ms, `brown_scores` 13KB < 500ms) |
| `test_whisper_voting.py` | 43 | Multi-temperature voting: agreement, word-level disagreement detection, `<END>` sentinel, total disagreement, empty transcription, low-confidence segment extraction, block suspect flagging |
| `test_clipboard.py` | 31 | `ClipboardPredictor` cache TTL, `invalidate()`, situation filtering, `compute_brown_scores` integration, prep > clipboard > fallback priority chain, `_build_bias` structure, min triggers threshold |
| `test_paralinguistic.py` | 49 | `compute_hnr` (synthetic ground truth: pure tone, noise, mixed, thresholds, degenerate inputs), `_classify_from_error_patterns` (S/D/I mapping, no_speech_prob, disagreement clusters), `detect_paralinguistic_events` (integration: noisy + clean audio, HNR exemption, duration gates), `format_paralinguistic_tags`, LAYERS/LAYER_NAMES constants |
| `test_prosodic.py` | 51 | `extract_f0` (synthetic pitch detection), `extract_prosodic_features` (per-segment F0/energy/rate), `compute_speaker_baseline` (historical averages), `infer_speaker_state` (stress/fatigue/calm/tension), `build_prosodic_context` (prompt formatting with stutter rules), `compute_prosodic_summary` (session-level aggregation) |
| `test_adversarial.py` | 198 | Stress/boundary/Unicode tests for all clinical features (run locally, not in CI) |
| **Total** | **1034** | **All passing** |

**Not yet tested** (require live API or audio hardware): Whisper transcription, LLM reconstruction, Falcon validation, DAF audio streaming.

## Changelog

### 2026-03-21 — Dashboard UX overhaul + architecture cleanup

- **Changed**: Situations collapsed from 6 to 3 (Default, High Stress, Reading). Phone/Presentation/Interview merged into High Stress. Casual merged into Default. Old names work via `_SITUATION_ALIASES` back-compat map.
- **Changed**: Layer 2 (Reconstruct) no longer injects vocabulary/corrections — that's now Layer 3 (Profile) only. L2 = generic LLM cleanup, L3 = personalized with your speech data.
- **Added**: Paralinguistic Transcribe sub-toggle — when ON, detected events ([Laughter], [Cough], etc.) are injected into pasted text. When OFF, events still logged but text stays clean.
- **Added**: Layer-aware UI — Tone and Mode sections collapse with "select Reconstruct +" hint when Layer 1 is active. No more clicking buttons that do nothing.
- **Added**: Inline descriptions for all layers, modes, and situations in the sidebar.
- **Added**: Interactive help manual overlay (accordion-style, matching dashboard aesthetic, pulsing ? button).
- **Added**: Hardware boot-up animation on dashboard load (panels fade in, numbers count up).
- **Added**: Compact mode redesign — minimal floating bar with essential controls.
- **Added**: Clickable timer reset on the main dial.
- **Added**: Toggle cooldown system — prevents 750ms poll cycle from snapping toggles back (2-second guard).
- **Added**: Hover-to-opaque card treatment across Sessions, Learning, Calibrate, and Insights tabs.
- **Fixed**: `test_endpoints.py` — 5 broken assertions fixed, 77 new assertions added (DAF, calibration, augment, toggle auto-enable, situation aliases). Total endpoint assertions: 170.
- **Fixed**: CRLF line endings preserved in dashboard.html.
- **Tests**: 1034 assertions passing across 14 test suites (up from 943).

### 2026-03-15 — Layer 5.5: Prosodic Bridging

- **Added**: Per-segment prosodic feature extraction (`extract_f0`, `extract_prosodic_features`) — F0 via autocorrelation, energy, rate, pitch direction per Whisper segment.
- **Added**: Speaker baseline computation from historical sessions (`compute_speaker_baseline`). Running F0/energy/rate averages stored in profile. Deviations expressed in sigma units.
- **Added**: Speaker state inference (`infer_speaker_state`) — maps prosodic deviations to natural language descriptions: stress, fatigue, vocal tension, calm.
- **Added**: Prosodic context formatting (`build_prosodic_context`) — rich per-segment acoustic transcript injected into GPT prompt at Layer 5. Includes stutter-specific disambiguation rules.
- **Added**: Automatic situation inference suggestion — elevated prosodic stress (>1.5σ) triggers logged suggestion, no auto-switch.
- **Added**: `prosodic_summary` column in sessions table for long-term prosodic trend tracking.
- **Added**: Speaker state indicator in dashboard sidebar.
- **Research basis**: USDM (Kim et al., NeurIPS 2024), SpeechEmotionLlama (Kang et al., Interspeech 2025).
- **Tests**: 51 new assertions in `test_prosodic.py`.

### 2026-03-15 — Layer 5: Paralinguistic Event Detection

- **Added**: Layer 5 (Paralinguistic) — detects non-verbal events in audio using HNR analysis + Whisper error pattern signatures.
- **Detection**: `compute_hnr()` (autocorrelation-based Harmonics-to-Noise Ratio), `_classify_from_error_patterns()` (Zhang's ASR error-type mapping: S+D → laughter, insertions → sigh/throat-clearing), `detect_paralinguistic_events()` (multi-signal pipeline with ±1s temporal gating).
- **Phase 1 tags**: `[Laughter]`, `[Cough]`, `[Sigh]`, `[Pause]`, `[Throat-clearing]`, `[Breathing]`.
- **Pipeline integration**: Detected events injected into `reconstruct()` prompt at L5 — tells the LLM to ignore Whisper hallucinations near paralinguistic timestamps.
- **Dashboard**: Layer 5 option in layer selector, paralinguistic event indicator in sidebar.
- **Database**: `paralinguistic_events` column added to sessions table (auto-migration).
- **Tests**: 49 new assertions in `test_paralinguistic.py` (HNR ground truth, error-pattern classification, integration detection, tag formatting, constants).
- **No new dependencies**: HNR computation uses existing numpy/scipy only.

### 2026-03-15 — Brown verification + test coverage update

- **Added**: `docs/browns_verification.md` — factor-by-factor verification of the phonetic risk model against Brown's 1945 paper with page citations and table data.
- **Updated**: Test coverage section — now reflects all 4 test suites (~336 assertions across 39 groups), up from the previous 95 across 2 suites.

### 2026-03-14 — Bug fixes

- **Fixed**: Covert pair removal endpoint (`/api/covert/remove`) was navigating a non-existent data structure (`substitutions`/`total_events` keys). Rewritten to use the actual `covert_profile.avoidance_pairs` structure.
- **Fixed**: Mobile transcribe endpoint (`/api/transcribe`) passed `low_confidence=` and `disagreements=` to `reconstruct()`, which silently ignored them. Corrected to `whisper_low_conf=` and `whisper_disagreements=`.
- **Fixed**: Dashboard HTTP server used single-threaded `HTTPServer`. During LLM calls (3–10s), all other requests queued, causing "CONNECTION LOST" in the dashboard. Replaced with `ThreadingHTTPServer`.
