# Apple + Stanford Research Integration — Build Spec for Sonnet

## Repo: `C:\Users\georg\Documents\GitHub\lavrentiy\`
## Engine: `lavrentiy.py` (~6,490 lines, single file)
## Dashboard: `dashboard.html` (single file, served on localhost:7878)
## WiM API: `wim/api/reconstruct.py`

IMPORTANT: Read `lavrentiy.py` and `CLAUDE.md` before making changes. The engine is a single monolithic Python file. All functions must be defined ABOVE where they're called (module-level execution, top-to-bottom). Thread safety is critical — see CLAUDE.md for lock patterns.

---

## TASK 1: Reconstruction Prompt Upgrade [smallest change]

### File: `lavrentiy.py`
### Find: The Layer 2+ reconstruction system prompt (search for `def reconstruct(` or the string that starts with "You are a voice reconstruction engine" or similar)

Add this paragraph to the reconstruction prompt, BEFORE the existing disfluency-specific instructions:

```
The transcription was produced by an automatic speech recognition system and may contain artifacts from speech disfluency including repeated words, repeated syllables, filler sounds, and silence where the speaker was blocked. When the literal transcription doesn't make grammatical sense, prioritize semantic intent and grammatical coherence over literal word sequence. Reconstruct what the speaker most likely intended to say, not what the microphone literally captured.
```

### File: `wim/api/reconstruct.py`
### Find: `build_prompt()` function

Add the same paragraph to the system prompt built by this function.

---

## TASK 2: Patience Mode

### What: Extend the silence timeout when Layer 4 (Stutter) or High Stress situation is active.

### File: `lavrentiy.py`

#### Step 1: Add configuration constants near the top (after existing constants):
```python
# Patience mode — extended silence threshold for PWS (Apple ML Research, 2023)
# Default endpointer cuts off PWS 23.8% of the time. Extending to 4.5s reduces to <3%.
PATIENCE_DEFAULT = 2.0   # seconds — normal silence threshold
PATIENCE_STUTTER = 4.5   # seconds — Layer 4 / High Stress
```

#### Step 2: Find where recording stops on silence detection.
Search for the recording logic — likely in `start_recording()` / `stop_recording()` or the audio callback. The silence detection probably checks if audio energy is below a threshold for N seconds. Make that N configurable:

```python
def get_patience_timeout() -> float:
    """Return silence timeout based on current layer and situation."""
    if current_layer >= 4 or current_situation == "high_stress":
        return PATIENCE_STUTTER
    return PATIENCE_DEFAULT
```

Use `get_patience_timeout()` wherever the silence threshold is currently hardcoded.

NOTE: Lavrentiy uses push-to-talk (F9 hold), not voice activity detection. The "patience" here applies to the post-release processing — how long the system waits for trailing speech before finalizing. If there's no silence detection in the current code (because F9 release = stop), then add this to the Whisper API call's `no_speech_prob` threshold instead:
- Default: `no_speech_threshold = 0.15`
- Layer 4 / High Stress: `no_speech_threshold = 0.6` (more tolerant of silence in audio)

#### Step 3: Add dashboard slider
In `dashboard.html`, add a "Patience" slider in the sidebar near the DAF controls:
- Label: "PATIENCE" (same style as DAF label)
- Range: 1.0 to 6.0 seconds, step 0.5
- Default: 2.0 (auto-sets to 4.5 on Layer 4 / High Stress)
- Shows current value in seconds

#### Step 4: Add API endpoint
```python
# In DashboardHandler.do_GET:
elif self.path == '/api/patience':
    self._json({"patience": get_patience_timeout()})

# In DashboardHandler.do_POST:
elif self.path == '/api/patience':
    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    global PATIENCE_DEFAULT, PATIENCE_STUTTER
    if 'default' in body:
        PATIENCE_DEFAULT = float(body['default'])
    if 'stutter' in body:
        PATIENCE_STUTTER = float(body['stutter'])
    self._json({"ok": True, "patience": get_patience_timeout()})
```

---

## TASK 3: Smart Repetition Classification

### File: `lavrentiy.py`
### Find: `strip_disfluencies()` function (or `def strip_disfluencies`)

#### Step 1: Add a set of naturally repeating English phrases (define ABOVE strip_disfluencies):
```python
# Natural English repetitions that should NOT be stripped (Apple ML Research, 2023)
# These are grammatically valid constructions, not disfluencies
NATURAL_REPEATS = {
    "had had", "that that", "is is", "was was", "do do",
    "can can", "no no", "bye bye", "so so", "very very",
    "go go", "now now", "come come", "well well",
    "out out", "boo boo", "ha ha", "ho ho",
    "knock knock", "tsk tsk", "aye aye",
    # Russian
    "да да", "нет нет", "ну ну",
}
```

#### Step 2: Modify the word repetition stripping logic
In the part of `strip_disfluencies()` that removes consecutive repeated words, add a check:

```python
# Before stripping a repeated word, check if it's a natural repetition
repeated_phrase = f"{word} {word}".lower()
if repeated_phrase in NATURAL_REPEATS:
    continue  # Don't strip — this is natural English
```

#### Step 3: For phrase repetitions, same principle:
Check if the repeated phrase is a common naturally-repeated construction before stripping.

---

## TASK 4: Longitudinal Clinical Profile Generator

### File: `lavrentiy.py`
### Where: Add after the existing `generate_weekly_report()` function (or similar report function)

#### New function: `generate_clinical_profile()`

```python
def generate_clinical_profile(min_sessions: int = 20) -> dict:
    """Generate a longitudinal disfluency profile from accumulated session data.

    Returns a structured dict suitable for display, PDF export, or API response.
    Requires min_sessions before generating (default 20).
    """
    sessions = db_get_sessions(limit=500)  # Get all available sessions

    if len(sessions) < min_sessions:
        return {"error": f"Need {min_sessions} sessions, have {len(sessions)}"}

    # Compute profile from session data
    # ... (implementation below)
```

The function should compute and return:

```python
{
    "user": profile.get("name", "Unknown"),
    "period": {"start": first_session_date, "end": last_session_date},
    "total_sessions": len(sessions),
    "total_minutes": sum(s.get("duration", 0) for s in sessions) / 60,

    "primary_disfluency": {
        "type": "syllable_repetition",  # most frequent type
        "percentage": 62,  # % of all disfluency events
    },
    "frequency_per_minute": 4.2,
    "frequency_trend": -18,  # negative = improving

    "situational_breakdown": {
        "default": {"rate": 2.8, "label": "baseline"},
        "high_stress": {"rate": 7.1, "vs_baseline": "+154%"},
        "reading": {"rate": 1.2, "vs_baseline": "-57%"},
    },

    "top_onset_triggers": [
        {"onset": "/k/", "weight": 0.87, "events": 23},
        {"onset": "/p/", "weight": 0.72, "events": 18},
        # ...
    ],

    "covert_avoidance": {
        "active_pairs": 7,
        "avoidance_rate": 34,  # % of high-risk words avoided
        "trend": "decreasing",  # was 41% four weeks ago
    },

    "fluency_trend": {
        "scores": [0.42, 0.44, 0.47, ...],  # per-session
        "improvement": 38,  # % improvement first→last quartile
    },

    "editorial_distance": {
        "average": 0.31,
        "trend": "decreasing",  # improving
    },

    "exposure": {
        "average_band": "moderate",
        "average_score": 0.35,
        "high_difficulty_sessions_pct": 12,
    },
}
```

Data sources — all from existing SQLite columns in sessions table:
- `disfluency_count`, `word_count` → frequency per minute
- `edit_dist` → editorial distance
- `exposure_score`, `exposure_band` → exposure difficulty
- `situation` → situational breakdown
- `language` → language breakdown
- Onset triggers from `profile["onset_weights"]`
- Covert avoidance from `profile["covert_profile"]`
- Fluency scores from `/api/fluency` logic

#### API endpoint:
```python
# GET /api/clinical_profile
elif self.path == '/api/clinical_profile':
    profile_data = generate_clinical_profile()
    self._json(profile_data)
```

#### Dashboard button:
In `dashboard.html`, add a "Clinical Profile" button next to the existing Weekly Report button in the Learning/Insights tab. On click, fetch `/api/clinical_profile` and display the result in a modal or new tab. Use the same formatting style as the weekly report.

---

## TESTING

After all changes, run ALL test files:
```
python test_core.py
python test_pipeline.py
python test_endpoints.py
python test_clinical.py
python test_integration.py
```

If any test fails, fix it. If a new endpoint was added, add a test for it in `test_endpoints.py`.

## RULES

- Do NOT restructure or refactor existing code
- Do NOT change function signatures of existing functions
- Do NOT modify test files unless adding new tests for new functionality
- All new functions must be defined ABOVE where they're called
- Thread safety: any new shared state needs a lock
- Python 3.10+ syntax only
- Test with `python lavrentiy.py` (not pythonw) to see errors
