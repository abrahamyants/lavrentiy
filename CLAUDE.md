# CLAUDE.md — Lavrentiy Voice Reconstruction Engine

## Architecture
- Single-file engine: `lavrentiy.py` (~275KB, ~5900 lines)
- Single-file dashboard: `dashboard.html` (~213KB)
- Profile dir: `~/.lavrentiy/` (profile.json, history.db)
- Layers: 1=Transcribe, 2=Reconstruct (generic LLM), 3=Profile (+ vocabulary/corrections), 4=Stutter (stack — each includes all below)
- L2 vs L3: vocabulary/corrections inject at layer >= 3, NOT layer >= 2. L2 is generic cleanup.
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
- 14 test files exist: test_core, test_pipeline, test_prosodic, test_paralinguistic, test_endpoints, test_adversarial, test_clinical, test_threads, test_clipboard, test_fuzz, test_perf, test_whisper_voting, test_pending, test_integration
- Run with: `pytest` from repo root
- RUN TESTS AFTER EVERY CHANGE. No exceptions.

## Safety Rules
- NEVER write to `C:\Users\georg\lavrentiy.py` without reading it first
- NEVER push to GitHub without verifying file content matches intent
- NEVER push large files (>100KB) through GitHub MCP create_or_update_file — content gets truncated
- If a fix requires restart, test with `python lavrentiy.py` (visible errors) before `pythonw`
