# Research Integration Plan — Lavrentiy

## Source Papers
1. Apple ML Research — "Improved Speech Recognition for People Who Stutter" (May 2023)
2. Stanford GSE — "The Sound of Syntax" (EMNLP 2025 Oral)

---

## BUILD TASKS (ordered by effort)

### TASK 1: Reconstruction Prompt Upgrade [2 minutes]
**Source:** Apple Intervention 2 (decoder tuning principle)
**File:** `lavrentiy.py` — Layer 2+ reconstruction prompt
**Change:** Add to system prompt:
```
The transcription may contain artifacts from speech disfluency including repeated
words, repeated syllables, filler sounds, and silence where the speaker was blocked.
When the literal transcription doesn't make grammatical sense, prioritize semantic
intent and grammatical coherence over literal word sequence. Reconstruct what the
speaker most likely intended to say, not what the microphone literally captured.
```
**Also add to:** `wim/api/reconstruct.py` — `build_prompt()` function

### TASK 2: Patience Mode [20 minutes]
**Source:** Apple Intervention 1 (endpointer tuning)
**File:** `lavrentiy.py` — recording stop logic
**What:** When Layer 4 (Stutter) is active, extend silence threshold before deciding the user stopped talking.
**Implementation:**
- Add `PATIENCE_DELAY` config: default 2.0s (normal), 4.5s (Layer 4)
- Make it user-adjustable via dashboard slider and `/api/patience` endpoint
- On Layer 4 activation (or High Stress situation), auto-set to 4.5s
- On Layer 1-3, use default 2.0s
- Dashboard: add slider in sidebar under DAF controls
**Stats:** Apple reduced truncation from 23.8% to 2.5% with 1.2s added delay

### TASK 3: Smart Repetition Classification [1-2 hours]
**Source:** Apple Intervention 3 (n-gram dysfluency refinement)
**File:** `lavrentiy.py` — `strip_disfluencies()` function
**What:** Before regex strips a repeated word/phrase, check if it's natural English or a disfluency.
**Implementation — Option A (no API call, fast):**
```python
# Built-in set of naturally repeating phrases
NATURAL_REPEATS = {
    "had had", "that that", "is is", "was was",
    "do do", "can can", "no no", "bye bye",
    # ... expand from corpus analysis
}

def is_natural_repetition(phrase: str) -> bool:
    return phrase.lower() in NATURAL_REPEATS
```
**Implementation — Option B (LLM, smarter but adds latency):**
```python
# Before stripping, ask the LLM:
# "Is '{word} {word}' a natural English construction or a speech disfluency?"
# Only at Layer 2+ where we already have the LLM call
```
**Recommendation:** Start with Option A (zero latency), add Option B as a toggle for Layer 4

### TASK 4: Longitudinal Disfluency Profile Report [2-3 hours]
**Source:** Stanford finding — single-shot diagnosis fails, profiling over time works
**File:** `lavrentiy.py` — expand `generate_weekly_report()` or create new `generate_clinical_profile()`
**What:** After N sessions (configurable, default 20), generate a structured clinical disfluency profile.
**Output format:**
```
DISFLUENCY PROFILE — [User Name]
Period: [date range], [N] sessions, [total minutes]

PRIMARY DISFLUENCY TYPE: Syllable repetitions (62% of all events)
FREQUENCY: 4.2 disfluencies/minute (down from 5.1, -18%)
SECONDARY: Prolongations (24%), Blocks (14%)

SITUATIONAL BREAKDOWN:
  Default:     2.8/min (baseline)
  High Stress: 7.1/min (+154% vs baseline)
  Reading:     1.2/min (-57% vs baseline)

PHONETIC TRIGGERS (top 5 onsets):
  /k/: 0.87 weight (23 events)
  /p/: 0.72 weight (18 events)
  /cr/: 0.65 weight (12 events)
  /str/: 0.61 weight (9 events)
  /b/: 0.58 weight (8 events)

COVERT AVOIDANCE:
  Active pairs: 7 (door→entrance, because→since, ...)
  Avoidance rate: 34% of high-risk words avoided
  Trend: decreasing (was 41% four weeks ago)

FLUENCY TREND:
  Week 1: 0.42 → Week 8: 0.58 (+38% improvement)
  [sparkline data]

EDITORIAL DISTANCE:
  Average: 0.31 (moderate reconstruction needed)
  Trend: decreasing (improving — raw speech closer to intent)

EXPOSURE DIFFICULTY:
  Average band: moderate (0.35)
  High-difficulty sessions: 12% of total
```
**Data source:** All from existing SQLite `history.db` — sessions table has disfluency counts, edit distance, exposure scores, paralinguistic events, onset triggers. No new data collection needed.
**Exportable as:** PDF (via reportlab or HTML→print), JSON (for API consumers), plain text
**Dashboard:** Add a "Clinical Profile" button next to the existing "Weekly Report" button

### TASK 5: FluencyBank/SEP-28k Fine-Tuning [weeks — moat]
**Source:** Stanford finding — fine-tuning on clinical data dramatically improves performance
**Datasets:**
- FluencyBank (https://fluency.talkbank.org/) — labeled stuttered speech, multiple languages
- SEP-28k (https://github.com/apple/ml-stuttering-events-dataset) — 28,000 clips labeled by disfluency type (Apple's own dataset, open-sourced)
**What:** Train a lightweight classifier to replace/augment regex-based `strip_disfluencies()`
**Architecture:** Fine-tune Whisper (or a small classifier head on Whisper embeddings) to output disfluency labels per segment: REPETITION, PROLONGATION, BLOCK, INTERJECTION, CLEAN
**Key insight:** Children's data is valuable because children stutter without masking. A model trained on raw childhood stuttering crushes adult masked stuttering.
**Timeline:** Research + data prep (1 week), training (2-3 days), integration (1 week)
**Moat factor:** HIGH — no consumer app has done this

---

## OUTREACH CONTACTS

### 1. Stuttering Foundation of America
**Contact:** Jane Fraser (President)
**Why:** Largest stuttering nonprofit worldwide (est. 1947). Funds research. Trains SLPs. Gateway to clinical network.
**Pitch angle:** Longitudinal profiling + reconstruction approach (different from everything in current research)
**Email:** Available on stutteringhelp.org

### 2. Michael Palin Centre for Stammering (London)
**Contacts:** Ali Berquez (Clinical Lead), Sarah Delpeche (Operational Lead)
**Why:** Premier UK/European clinical centre. NHS-supported. Trains SLPs internationally.
**Pitch angle:** Auto-generated disfluency profiles as supplementary therapy tool
**Note:** They say "stammering" not "stuttering"

### 3. Stanford — Sang Truong / Nick Haber / Sanmi Koyejo
**Why:** Published EMNLP 2025. Showed 15 LLMs fail at single-shot diagnosis. Actively seeking solutions. HELM benchmark integration.
**Pitch angle:** Longitudinal profiling sidesteps the single-shot limitation they identified. Our aggregated data could complement their benchmark.
**Bonus:** Jody Vaynshtok (SLP on the team) is San Francisco-based — local meeting possible.

### 4. Apple ML Research
**Why:** Published the most comprehensive PWS+ASR study. Identified 3 intervention points. We implemented all 3 + a 4th they didn't attempt.
**Pitch angle:** Our approach complements their published findings. LLM reconstruction sidesteps ASR accuracy limitations.
**Contact:** Colin Lea, Zifang Huang (from acknowledgments) — find via LinkedIn/academic profiles

---

## PITCH AMMUNITION (from Apple survey)

| Statistic | Lavrentiy's Answer |
|-----------|-------------------|
| 61% of PWS say VAs cut them off | Patience mode — extended silence threshold |
| 57.6% say VAs don't understand them | Reconstruction — intent over transcription |
| 37.3% don't want others to hear them | Text-based output, not speaking to a VA |
| 22% say too much physical effort | Stream of consciousness, no proofreading |

---

## POSITIONING

Apple: Fixed ASR at the system level. WER 25% → 8%. Better transcription. Still broken. Still requires proofreading.

Stanford: Benchmarked 15 LLMs on clinical diagnosis. None hit 80%. Single snapshots aren't enough.

Лаврентий: Lets ASR fail. Reconstructs intent via LLM. Builds longitudinal profiles over time. Three levels of innovation:
1. Apple's approach IMPROVED (patience + smart filtering)
2. Stanford's limitation SIDESTEPPED (profiling not diagnosing)
3. Longitudinal capability NEITHER attempted
