# Session Log — 2026-04-04/05 (Lavrentiy)

## SHIPPED (committed, pushed, portable synced)

### Auth / GDPR
- Google Sign-In working (system browser redirect, `auth_google.html` brand-matched)
- Export/delete data endpoints (engine API + Cloud Function deployed)
- GDPR export filter (strips internal fields: `daily_count`, `tier`, `daily_reset`)
- PRIVACY.md updated (Firestore sync scope, 24-month retention policy)
- "Free tier" → "Invite" rename

### Sidebar + Dashboard UI
- Frozen sidebar (top pinned, bottom scrolls)
- D/L theme toggle relocated next to compact button (left side, next to EN/RU)
- Dark mode as default
- Quiet Mode merged into Enhancements section (Voice section removed)
- Enhancements: Paralinguistic + Prosodic consolidated into single card
- Click-to-record on "idle" label (mouse alternative to F9)
- All stat/learn bar cells clickable → navigate to relevant tab
- Hover states on learn cells + progress cells (orange glow)
- Fluency metric replaces "Next Cycle" readout
- Legacy profile dropdown removed
- Status ring poll rate: 750ms → 250ms (faster visual feedback)

### Console
- Color legend bottom-right (brand colors, stacked vertically, compact)
- Tips toggle bottom-left (brass-styled, mirror of legend)
- Daily tip banner (15 tips, rotates by day-of-year, dismissible per-day)
- Context-aware typewriter hint under status ring (rotates hints based on layer/state/toggles)
- Console order reversed (newest entries at top)
- Horizontal scrollbar killed

### Engine / Pipeline Fixes
- 180s safety timeout (was 30s)
- Pre-roll buffer (500ms always-on ring buffer, catches first word)
- F9 push-to-talk restored (reverted broken toggle spam)
- Whisper hallucination filter ("Transcribed by otter.ai", "Thanks for watching", etc.)
- Whisper repetition loop detection (compression_ratio > 2.4)
- "Loops" readout in learn bar
- Covert avoidance preset bug fixed (hardcoded "Hello this is speaking. Thank you for having me. Next slide." removed from high_stress — was polluting covert_profile with garbage pairs)
- 6 polluted covert pairs cleaned from profile
- Filler word merge from WiM (uhm/umm/erm/hm/hmm + Russian эм/нуу)
- Repetition threshold 2 → 3 (preserves emphatic "no no", "please please")

### Audit Fixes (from earlier full pipeline audit)
- Onset weights persistence to profile JSON (was silent data loss bug)
- L2/L3 Whisper confidence passing (was L4-only)
- L2/L3 speech severity passing
- `analyze_speech_rate()` at L2+ always
- F11 `cycle_layer()` → `set_layer()` (auto-prosodic on L4)
- `strip_block_hallucinations()` at all layers (was L1-only)
- `apply_profile_corrections()` at L2+ (was L3+)
- Falcon validation now tone-aware
- Reading situation DAF fix
- Dead `_REPEAT_WORD` regex removed
- Backend paralinguistic/prosodic pass-through (Cloud Function deployed)

### New Features
- **Quiet Mode toggle** (audio AGC target -12dB → -6dB, high-pass 70Hz → 100Hz)
- **Command Mode (F8)** — select text in any app, hold F8, speak command, release → selection replaced with transformed text. Clipboard save/restore.
- **"You" tab** — Voice Profile reframe (celebratory stats at 500+ words: headline, catchphrase, peak time, superpower, day streak)
- **Network status Wi-Fi bars** in API Calls stat cell (green/red/idle)
- **RESET HISTORY + DELETE PROFILE** buttons in The File tab
- **Command Mode intro banner** (first-time discovery after 10 sessions)
- **Splash screen** on startup (instant window, Playfair brand plate, animated equalizer, rotating status messages)
- **Mic level equalizer** flanking status ring (14 bars, independent chaotic motion, 7 per side)
- **Status ring CMD state** (amber/gold when F8 held, distinct from red recording)

### Help Manual
- Updated with all new features: Command Mode, Quiet Mode, You Tab, Privacy, Loops/Blocks
- Hotkeys section includes F8

### Gemini 2.5 Pro Integration
- `gemini_client.py` — HTTP client for generateContent API
- Routing: L2/L3 → Gemini (if `GEMINI_API_KEY` set), L4 → GPT-4o (unchanged), Falcon → GPT-4o
- Auto-fallback to GPT-4o on Gemini failure (MAX_TOKENS, network, etc.)
- Log line now includes model tag: `[gpt-4o]` or `[gemini-2.5-pro]`
- `max_tokens=4096` (Gemini 2.5 Pro "thinking tokens" eat output budget)
- Portable path fix: `sys.path.insert(0, script_dir)` so sibling imports work in embedded Python

### Cloud Function (WiM backend, deployed)
- Tier limits updated: all tiers (Invite/Basic/Pro) now max_layer=4
- Daily limits unchanged: 30/200/unlimited
- Paralinguistic/prosodic context plumbed through
- Export filter strips internal fields

## WHAT DIDN'T WORK (tried and reverted)
- **Layer-aware Whisper gating** (L1 → local faster-whisper, L2+ → API)
  - Reverted because local faster-whisper on consumer CPU is often slower than API round-trip
  - faster-whisper stays as fallback-only when API fails
- **Vertical resize handle** (to resize top stats bar height)
  - Reverted because behavior was opposite of expected
- **Command Mode modal popup**
  - Replaced with inline dismissible banner in brand colors

## STILL OPEN / DEFERRED
- **#9 `strip_disfluencies` before L4 reconstruction** (known audit bug, risky refactor)
- **Retention cron** — auto-delete Firestore docs after 24mo inactivity (policy documented in PRIVACY.md, not enforced)
- **Quiet Mode Phase 2** — auto-detection via ZCR + low energy + flat spectrum
- **Safety rules** — password field / banking URL auto-disable
- **Voice Profile GPT version** — current insights are algorithmic
- **Recording indicator outside pywebview** (if window minimized)
- **Reset profile confirmation UX refinement**

## NOT YET TESTED LIVE (shipped, needs real session verification)
- Falcon tone-awareness (needs formal-tone recording)
- Reading DAF stop
- Command Mode in real apps (Gmail, Word, Slack)
- Gemini 2.5 Pro path (key activated; first test hit MAX_TOKENS, then import error, then fixed — needs fresh test)

## KNOWN QUIRKS
- Gemini 2.5 Pro "thinking tokens" require generous maxOutputTokens (using 4096)
- Portable Python's `_pth` file doesn't auto-add script dir — fixed with `sys.path.insert(0, __file__)` at top of lavrentiy.py
- Covert avoidance heuristic assumes Script Prep text is semantically related to actual speech; false pairs generated if unrelated (fixed root cause: removed hardcoded preset template)
- DAF feedback loop on speakers — DAF designed for headphone use only

## PORTABLE STATE
- Size: 544 MB (unzipped)
- faster-whisper: installed, fallback-only
- All dashboard + engine files synced
- `gemini_api_key.txt` present (activated)
- `api_key.txt` present

## GIT STATE
- All commits pushed to `main` at github.com/gugosf114/lavrentiy
- Latest: Gemini integration + layer-aware gating revert

## SECURITY NOTE
- Accidentally committed `gemini_api_key.txt` to public GitHub in commit `c3c0f2b` before `.gitignore` was updated. Fixed in commit `3c7b549` (removed from tracking, added to .gitignore) but key is still in git history.
- Risk is bounded: Gemini API keys are scoped only to Gemini API (no access to Drive/email/etc), max damage is quota/credit exhaustion.
- **TODO:** In GCP Console → Billing → Budgets & Alerts, set a hard budget cap (e.g. $50/month). That's the real safety net against any key leak, not just this one. Rotate the key via https://aistudio.google.com/apikey when convenient.
