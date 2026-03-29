# CLAUDE.md — Lavrentiy Voice Reconstruction Engine

## Architecture
- Single-file engine: `lavrentiy.py` (~275KB, ~5900 lines)
- Single-file dashboard: `dashboard.html` (~254KB) — includes EN/RU i18n (184 translation keys)
- Profile dir: `~/.lavrentiy/` (profile.json, history.db)
- Layers: 1=Transcribe, 2=Reconstruct (generic LLM), 3=Profile (+ vocabulary/corrections), 4=Stutter (stack — each includes all below)
- L2 vs L3: vocabulary/corrections inject at layer >= 3, NOT layer >= 2. L2 is generic cleanup.
- Auto-learn runs at L2+ (not L3+). L2 raw→clean pairs feed the learner in the background so the profile is warm by the time L3 activates.
- Independent toggles: Paralinguistic (cough/laugh/HNR + transcribe sub-toggle), Prosodic (F0/energy/rate) — not layer-gated
- Prosodic auto-enables on Layer 4 (Stutter)
- Situations: 3 (default, high_stress, reading). Old names (phone, interview, presentation, casual) resolve via _SITUATION_ALIASES
- Dashboard UI: Tone/Mode collapse on L1, toggle cooldown (2s) prevents poll overwrite, hover-to-opaque cards

## Deployment
- VBS shortcut runs `C:\Users\georg\Documents\GitHub\lavrentiy\lavrentiy.py` (single source of truth)
- Dashboard served from `Path(__file__).parent / dashboard.html` — always the repo copy, no sync needed
- Dashboard polls /api/state every 750ms — toggle changes need 2s cooldown to avoid race condition snap-back
- Engine runs under `pythonw.exe` — errors are SILENT. Test with `python` first.

## Gotchas
- Python 3.14 on Windows uses cp1252 console encoding. Unicode chars (arrows, warning signs, etc.) crash `print()`. Wrap in try/except or use ASCII.
- Module-level code runs top-to-bottom. Functions called during import (migrate_profile, learn_onset_weights, ClipboardPredictor.start) can only reference functions defined ABOVE them.
- `keyboard` library needs the process to be running for hotkey hooks. Crashes during init = no F9.
- Single-instance mutex: only one engine process at a time. Kill old before restarting.

## Testing
- 19 test files, ~1,285 assertions total. Run with `python <test_file>.py` (not pytest — test files use sys.exit at module level)
- RUN TESTS AFTER EVERY CHANGE. No exceptions.
- test_core (39 pass) — _extract_onset, learn_onset_weights, predict_phonetic_risk, compute_wer, risk_flags, make_decision
- test_pipeline (96 pass) — L1-L4 paths, all modes, critical token retention, covert avoidance chain, decision matrix
- test_prosodic (51 pass) — F0 extraction, speaker baseline/state inference, prosodic context building
- test_paralinguistic (49 pass) — HNR computation, error-pattern classification, event detection, tag formatting
- test_endpoints (170 pass) — all 21 HTTP routes, CORS, 404s, JSON response shapes
- test_adversarial (198 pass) — 16 categories of hostile input (null bytes, emoji, None, malformed dicts)
- test_clinical (95 pass) — exposure, editorial distance, covert avoidance, decay
- test_threads (37 pass) — 8 concurrent scenarios: shadow history, stats, preview, learn events, onset anomalies, profile lock contention, HTTP state mutations
- test_clipboard (31 pass) — ClipboardPredictor scoring, cache TTL, situation filtering
- test_fuzz (23 pass) — 12 functions x 6,000+ random inputs (ASCII, Unicode, massive strings)
- test_perf (19 pass) — 12 functions with ms thresholds for regression detection
- test_whisper_voting (43 pass) — multi-temp agreement, low-confidence segments
- test_integration (53 pass) — disfluency filtering (EN+RU), DB schema round-trip, profile migration
- test_pending (127 pass) — 9 functions that previously had zero coverage
- test_preview (14 pass) — start/stop/update preview stream, set_state
- test_profile_db (83 pass) — profile lifecycle (load/save/migrate/switch/create), DB schema migration, log_session 17-column round-trip, concurrent writes
- test_audio_preprocess (29 pass) — DC removal, 70Hz high-pass Butterworth, AGC -12dB normalization, tanh soft clip, frequency response verification
- test_wim_api (95 pass) — WiM consumer API: strip_disfluencies, build_prompt (tones/layers/situations/Whisper signals/covert avoidance), compute_confidence, mocked reconstruct_intent (all modes/layers/falcon reject), response shape contract, live 100-concurrent stress test (skips if no API key)
- test_speech_rate (33 pass) — analyze_speech_rate: synthetic audio with controlled pause ratios, syllable onset counting, severity modifier thresholds, slow rate detection, edge cases (tiny/long/silence signals)

## Thread Safety
- _profile_lock guards all save_profile() calls (20 call sites across HTTP, hotkey, learn, and pipeline threads)
- _db_lock guards all SQLite writes. switch_profile holds _db_lock across close + reinit to prevent use-after-close.
- _profile_switch_epoch: background threads capture epoch at launch, bail if it changes before saving (prevents cross-profile corruption)
- _shadow_lock, _learn_lock, _stats_lock, _prep_lock, preview_lock, _redo_lock, _augment_lock for respective shared state
- save_profile uses atomic tmp→fsync→rename pattern inside the lock

## Safety Rules
- NEVER write to `C:\Users\georg\lavrentiy.py` without reading it first
- NEVER push to GitHub without verifying file content matches intent
- NEVER push large files (>100KB) through GitHub MCP create_or_update_file — content gets truncated
- If a fix requires restart, test with `python lavrentiy.py` (visible errors) before `pythonw`
