# Lavrentiy — Claude Code Primer

## What this is
Windows voice-to-intent and communication-assistance tool. Researcher outreach is welcome, but the app is not a clinical instrument, diagnosis, treatment, or severity measure. It processes captured audio/ASR text and cannot recover an unspoken word. Python desktop, Windows installer. Some reconstruction code is shared with WiM through the `wim-reconstruct` Cloud Function.

## Architecture

### Engine
- **Entry point (PyInstaller --onedir build)**: `lavrentiy_launcher.py` — starts the engine and opens either the native pywebview/WebView2 window or the browser fallback at `http://localhost:7878/`.
- **Engine**: `lavrentiy.py` — single-file Python, ~10,056 lines as of 2026-05-05. Module-level top-to-bottom execution (no `__main__` guard). Hotkey listener (F9 record / F10 tone / F11 layer / F12 stats / F3 triple-tap quit), audio capture, LLM pipeline, embedded `ThreadingHTTPServer` on :7878, dispatch table at `dispatch_api()` (line ~9443) so the same handlers serve HTTP and (formerly) QWebChannel paths.
- **Dashboard**: `dashboard.html` — single file, rendered in the native WebView2 window by default and also available at `http://localhost:7878/` as a browser fallback. Polls `/api/state` every 750ms (2s toggle cooldown to prevent poll snap-back).
- **Legacy native entry** (`desktop.py`, 348 lines): retained for history only. The current native route is `lavrentiy_launcher.py --native`, launched by `Lavrentiy-Native.vbs`.
- **Python**: 3.10+. George's machines run 3.13 (bundled) and 3.14 (system). Python 3.14 has known `httpx` / `huggingface_hub` breakage — stdlib urllib workarounds live in `eval-build/_fetch_fw_model.py`.

### Layer pipeline
| Layer | Name | What runs (as of 2026-05-05) |
|---|---|---|
| L1 Transcribe | ASR | Local **faster-whisper small.en** by default (English, offline) or optional cloud transcription. Toggle via Advanced → L1 SOURCE, `POST /api/l1_asr {cloud: bool}`. |
| L2 Reconstruct | Cloud GPT-4o, generic cleanup |
| L3 Profile | + vocabulary/corrections/triggers (vocab+corrections inject at L3+, NOT L2) |
| L4 Advanced | Uses richer ASR uncertainty and speech/profile context with the configured reconstruction route. Pause Bridge suggestions are context completions approved by the user, not recovered silent speech. |
| L5 Paralinguistic / L5.5 Prosodic | HNR + F0/energy/rate. L4-only — needs Whisper segment data. Greyed out on dashboard at L1/L2/L3. |

### Meaning guard
- `falcon_validate()` is a legacy no-op retained only for schema compatibility. Never claim that a second AI validates output.
- SAFE mode uses deterministic retention checks for names, numbers, dates, amounts, and negation. This is a limited guard, not semantic-equivalence proof.

### Auth flow
Firebase Auth supplies a Google ID token to `/api/auth`; signed-in backend transcription and reconstruction route through `wim-reconstruct`. User-provided fallbacks live only under `%USERPROFILE%\.lavrentiy\api_key.txt` and `%USERPROFILE%\.lavrentiy\anthropic_key.txt`. **Never bundle either key in a public installer.** Free local English Layer 1 requires no key.

### Language axes
- **Interface:** EN/RU. Russian copy loads from `lang_packs/dashboard_i18n_multilang.json` only when its recorded English source still matches current dashboard copy; current overrides cover deliberately rewritten text. This prevents stale clinical claims returning through translation drift.
- **Spoken dictation:** local `small.en` is English-only. Non-English uses authenticated backend audio transcription or a user-owned OpenAI key. Supported codes match current reconstruction packs: `ar,de,es,fr,hi,it,ja,ko,pt,ru,zh` plus `en`.
- **First-language English transfer:** the 10 `l1_packs` include Farsi. They apply to English reconstruction on L2/L3 and are not UI or spoken-dictation language packs.

### Profile + DB
- Multi-user: `~/.lavrentiy/profiles/<name>/{profile.json, history.db, backups/}`. Active profile name in `~/.lavrentiy/active_profile`.
- Profile schema v4. SQLite WAL mode. 18-column `sessions` table (April 24 evening added `triggers_fired`).
- Atomic save: tmp, then fsync, then rename, guarded by `_profile_lock` across 20 call sites.
- 9 dedicated locks: `_profile_lock`, `_db_lock`, `_shadow_lock`, `_learn_lock`, `_stats_lock`, `_prep_lock`, `preview_lock`, `_redo_lock`, `_augment_lock`.
- `_profile_switch_epoch`: background threads capture epoch at launch, bail if changed before saving (prevents cross-profile corruption).

## Historical state snapshot (as of 2026-05-10)

This section is retained for failure history and provenance. It is not the current release state; use the architecture and meaning-guard sections above plus `EVALUATOR_GUIDE.md`, `INSTRUCTIONS.md`, and the current code.

### Shipping path
- **v1.6.1 installer** built (`installer/Output/Lavrentiy-Setup-v1.6.1.exe`, 2026-05-07). PyInstaller `--onedir` (NOT `--onefile` — see DON'T list). Drift-proof: `[Files]` is one wildcard line, no manual file enumeration, so future imports auto-bundle. AppId `{B7E5F4A2-9C3D-4E1B-8A6F-2D8B5E9C1F3A}` (distinct from v1.5.7).
- Installs to `%LOCALAPPDATA%\Programs\Lavrentiy\` (per-user, no admin elevation).
- New launcher path: `lavrentiy_launcher.py` opens dashboard in default browser. **No more pywebview, no more Qt, no more `desktop.py` failure surface** as the primary path.
- v1.5.7 was the prior ship (548 MB, `Lavrentiy-Eval` AppId, manual `[Files]` enumeration — the drift cause that broke wife's-laptop install: fresh `lavrentiy.py` imports `domain_pack` / `l1_pack` / `rejection_store` / `style_examples` that .iss never grew alongside, leading to instant `ModuleNotFoundError`).
- v1.6.0 verified via architecture-only smoke (port 7878 binds, `GET /api/state` returns valid JSON, no `ModuleNotFoundError`). **Not verified end-to-end** (F9 hotkey, transcribe, reconstruct, paste). Wife's-laptop install pending.
- v1.6.1 followup: `collect_all('faster_whisper')` + `collect_all('ctranslate2')` pulled CUDA + ROCm + DirectML variants. CPU-only is needed; trim to drop installer well below 500 MB.

### Pre-outreach de-risking phase
Per `project_lavrentiy_current_mode`: holding foundation emails until heavy-stutter tests pass. Heavy-stutter harness (`test_heavy_stutter.py` + `heavy_stutter_test_scripts.json`, 18 cases) and acceptance criteria (`HEAVY_STUTTER_ACCEPTANCE_CRITERIA.md`: L4 WER 0.30 or less, Intent Jaccard 0.70 or more, Coverage 0.85 or more, Proper-noun 0.90 mean or more) are committed. First runs: L4 perfect on 12 of 18, struggled on 3 (h07 phone-stress avalanche, h12 doctor question, h18 block-then-substitution). Commodity GPT-4o baseline column added. Lav L4 distinctly outperforms vanilla GPT-4o on 3 of 18 cases (the Whisper-hallucination-contamination ones), matches on 14, loses h07 by 0.17 WER. Net: prompt-stack value concentrates in hallucination cleanup, not clean-disfluency cleanup. **The harness was run against the OLD installed engine on AppData**, NOT the post-prompt-stack-rebuild repo state.

### Bottleneck framing
Per `project_lav_bottleneck_is_launcher`: **launch UX is the ship-blocker, NOT recon prompt-stack quality.** v1.6.0 directly addresses this (drift-proof installer + browser-based UI). Recon work (ALWAYS RESTATE, slang preservation, domain packs, rate-gap, rejection store, style examples, audience context, PhoneticMatcher port, 10 L1-transfer packs) is real engineering but stays "backstage tweaks" framing — never pitch material. Foundation outreach is gated on "the app actually works when someone double-clicks it."

### Code signing
Deferred for V1. Lavrentiy has an Apache 2.0 license and a historical SignPath application, but the V1 research build ships unsigned with clear SmartScreen instructions. Do not delay V1 for signing.

### L1-transfer packs (10 languages)
- `lavrentiy/l1_packs/{russian,spanish,mandarin,hindi,arabic,farsi,french,german,korean,japanese}.json`. Source paper: `docs/L1_Transfer_Markers_in_Written_English.md` (40-page Gemini-generated research paper, primary source for adding new language packs).
- **Distributed across 4 destinations, MD5 byte-identical** — edit one, mirror to all 4 in the same commit:
  1. `lavrentiy/l1_packs/`
  2. `lavrentiy/wim/api/l1_packs/` (Cloud Function backend)
  3. `wim-android/app/src/main/assets/l1_packs/`
  4. `bakers-agent/wim-l1-guess-v1/l1_packs/` (auto-detect Cloud Function)
- Pref key: `profile_l1` on both sides. Lav reads via `prof.get("profile_l1") or prof.get("l1")` for legacy back-compat. WiM reads from SharedPreferences.
- `wim-reconstruct` Cloud Function deployed at revision `wim-reconstruct-00010-pej` (as of 2026-04-30) at `us-central1-bakers-agent.cloudfunctions.net/wim-reconstruct`. `wim-l1-guess` at revision `wim-l1-guess-00005-mox`.

### Native L1 picker UI
Currently must edit `~/.lavrentiy/profile.json` by hand. WiM Android has the Profile-screen dropdown; Lav does not. ~30 min addition to dashboard sidebar (deferred).

## Conventions

### Single-file engine constraints
- Functions called during import (`migrate_profile`, `learn_onset_weights`, `ClipboardPredictor.start`) MUST be defined ABOVE where they're called.
- Never use `from <project_name>.<module>` style inside the main script — Python's resolver picks up the script being executed, triggers recursive self-import. **The 2026-04-24 `from lavrentiy.firestore_publisher import` bug killed the engine on every save_profile call** — root cause for hours of "connection lost" debugging (FAILURE LOG #35).
- Module collision: had a `lavrentiy/` subpackage and `lavrentiy.py` script in same dir. Resolver picked subpackage first, leading to `AttributeError`. Fixed by renaming subpackage to `lavrentiy_pkg/` (2026-04-26).

### Threading
- Module-level locks listed in Architecture above. Always grab `_profile_lock` around `save_profile()`. Always grab `_db_lock` around SQLite writes; `switch_profile` holds `_db_lock` across close + reinit to prevent use-after-close.

### WiM Android parity (canonical values live HERE)
- `SITUATION_SEVERITY`: default=1.0, high_stress=1.5, reading=0.3
- `TONE_TEMP`: formal=0.1, professional=0.15, casual=0.35, friend=0.4
- Auto-learn gate: L2+ (NOT L3+)
- Backend payload keys: `vocabulary`, `corrections`, `filler_words`, `trigger_words`, `onset_weights`, `covert_profile`, `audience_package`, `language_code`
- PhoneticMatcher gate: **L1-L3 on both apps** (NOT L4) since 2026-08-29. It was
  L2/L3-only because a wrong swap at L1 has no model behind it; the guard it
  actually needed was the 296-word `profile_terms._APPROXIMATE_BLOCKLIST`, not a
  model. Unguarded, "I like it a lot" becomes "I luke it a lot". Pass it as
  `blocklist=`. L4 stays out - Sonnet ext-think reasons through phonetic context
  from the onset_weights block. Constants: `_PHONETIC_MIN_WORD_LENGTH = 3`,
  `_PHONETIC_HIGH_RISK_THRESHOLD = 0.5`. First-letter guard against b/p, t/d,
  k/g, m/n Double-Metaphone collisions.
- Spelled-out words: `collapse_spelled_words()` runs FIRST in
  `_clean_and_filter_text`, before any filter. A person who blocks spells the
  word - "E as in Edward, D. David" - and every pass below is built for prose.
  Floor is three letters so "PhD" and "the US" survive. Not yet in wim-android.
- `NATURAL_REPEATS` extended with 7 emphatic doublings (really, many, much, right, sure, okay, just) — protect 3+ case via the `(?:\s+\1){2,}` regex.

### Terminology (per `feedback_use_speech_disfluency` + `feedback_stutter_terminology`)
- **User-facing copy**: "speech disfluency", NOT "stuttering". Funnel argument — the broader audience is materially larger.
- **Research/clinical memos in `docs/`**: "stuttering" is fine — it's the technical term in academic literature. Keep citations accurate.
- **Code identifiers**: keep existing names (`STUTTER_FRAGMENT` regex, `covert_profile`, `onset_weights`, etc.) — changing them has no marketing value and risks bugs.
- **"Severe stutter"** = audible repetitions/prolongations. **"Hard speech block"** (or "hard block") = silent, no airflow — what George specifically has. Don't collapse them. Don't say "block-dominant speakers."

### Three-copies-of-dashboard.html trap
- Source repo: `lavrentiy/dashboard.html`
- PyInstaller dist: `dist-onedir/Lavrentiy/_internal/dashboard.html`
- Installed engine: `%LOCALAPPDATA%\Programs\Lavrentiy[-Eval]\engine\dashboard.html` — what the running engine actually reads via `Path(__file__).parent / 'dashboard.html'`.
- Edit the source, then copy to the live install copy (or rebuild + reinstall). Permanent fix (post-build hook) NOT implemented.

### Test discipline
- ~1,500+ assertions across 19 test files. Run with `python <test_file>.py` directly (NOT pytest — files use `sys.exit` at module level).
- RUN TESTS AFTER EVERY CHANGE.
- CI on GitHub Actions: `Tests` workflow + `pages-build-deployment`. Both went red for ~3 days in late April 2026 with nobody looking. `test_core.py:22` `exec()` of `const_block` from `lavrentiy.py` requires `os` in the namespace dict (broken when `os.environ.get(...)` was added to the LANGUAGE constants block). README Liquid syntax can break Pages build (`&#123;%USERPROFILE}` on line 1865 was an unterminated tag).
- See README "Test Coverage" table for per-suite assertion counts. New since old CLAUDE.md: `test_speech_rate.py` (33), `test_audio_preprocess.py` (29), `test_wim_api.py` (122), `test_pending.py` (127), `test_profile_db.py` (83).

## DO

- **Verify ASR/recon claims with actual heavy-stutter audio before declaring success** (per `feedback_name_commodity_baseline` — Drew Lynch in early years is NOT heavy-enough; Daisy is the kind of test, not Drew).
- **Inspect data against the ACTUAL criterion before categorizing** (per `feedback_inspect_data_before_categorizing` — plosive onset for stutter triggers, not "looks like tech vocab").
- **Check `engine_err.log` FIRST when "feels stuck" reports come in** — most silent hangs leave a captured traceback (FAILURE LOG #41 lost ~10 min before checking it; #53 lost 5-10 min reading working code when the real cause was Anthropic credit exhaustion).
- **When a credential is shared across projects and spend is unexpectedly high, enumerate ALL projects using that credential** before debugging any one of them (FAILURE LOG #54 — Lavrentiy was clean; bakers-agent SEO tool was burning the shared Anthropic key).
- **Edit `dist/Lavrentiy/_internal/dashboard.html` directly for "page won't render" debugging** — QtWebEngine reads it from disk on launch, no rebuild needed (30s iteration vs 25min PyInstaller rebuild).
- **Take a screenshot BEFORE writing CSS** when the instruction is "make X look like Y" (FAILURE LOG #43 — modified CSS twice without screenshots, both times George had to catch it). Tool: `mcp__chrome-devtools__take_screenshot`.
- **Maintain L1-L4 parity with wim-android** (per `feedback_lav_wim_parity`) — when proposing a stack change in one app, verify the same change lands in the other, flag asymmetries explicitly.
- **Before pinning a model URL into an install script, verify unauthenticated `curl -I` returns 200** — HF gated `Systran/faster-whisper-large-v3-turbo` to 401; pivoted to `deepdml/faster-whisper-large-v3-turbo-ct2`.
- **Before swapping a model that consumes `verbose_json`, run a one-shot curl to confirm the response format is still accepted** (FAILURE LOG #50 — `gpt-4o-transcribe` returns HTTP 400 on verbose_json; reverted to `whisper-1`).
- **When killing PyInstaller mid-build, also delete `build/` and `dist/`** — don't trust the background-task exit code as evidence of build completion (FAILURE LOG #81).
- **Test with `python lavrentiy.py` first to see errors** before launching via `pythonw.exe` (silent stdout/stderr).
- **For PowerShell from this harness: re-define `Add-Type` C# classes in EVERY tool call** — each invocation is a fresh session, registrations are session-local. Or move multi-step sequences into a single `PowerShell` call.

## DON'T

- **Don't break existing functionality** (per `feedback_dont_break_things` — #1 priority during multi-project active development).
- **Don't frame recon prompt-stack work as ship-blocker or pitch material** — launcher UX is the actual blocker (per `project_lav_bottleneck_is_launcher`).
- **Don't downgrade from "best" to "cheap" path** (per `feedback_recommend_best_not_cheap` — FAILURE LOG #45: led with gpt-4o-mini for L2/L3, George rejected). George cares about output quality first; compute budget is not the bottleneck.
- **Don't claim things are shippable / take credit for accidental wins** (per `feedback_dont_imply_shippable`).
- **Don't propose `--onefile` PyInstaller for the desktop app** — it re-extracts the ~660 MB bundle to `%TEMP%` on every launch (30-60s cold start). 2026-05-05 session almost repeated FAILURE LOG #78 verbatim before George flagged "PyInstaller shit sounds very familiar." Use `--onedir`.
- **Don't manually enumerate engine files in the `[Files]` block of the .iss script** — use the `dist-onedir/Lavrentiy/*` wildcard. Manual enumeration was the drift cause for v1.5.7 (`ModuleNotFoundError: domain_pack` on wife's laptop).
- **Don't use `taskkill /IM pythonw.exe /F`** — kills every pythonw process on the system including unrelated Python work. Use `_kill_engine_on_port(7878)` instead (FAILURE LOG #47).
- **Don't use `from <project_name>.<module>`** inside `lavrentiy.py` — recursive self-import kills the engine on first call (FAILURE LOG #35, #46).
- **Don't bundle a model without checking the auth/license gate** — and **don't strip-not-swap when removing a bundled local model**. v1.5.1 dropped the bundled Moonshine without replacing it with faster-whisper, broke offline-first L1. v1.5.7 ships `faster-whisper small.en` (~486 MB) bundled at `eval-build/models/faster-whisper/small.en/`.
- **Don't kill processes by image name when port-targeted, PID-targeted, or window-title-targeted alternatives exist.**
- **Don't propose a backend-proxy architecture George never asked for** (FAILURE LOG #2 — invented a "users without Replicate accounts" model; Lav is desktop-only, George is the operator).
- **Don't burn Replicate credits on Canary** — wired but `CANARY_ENABLED = False` since 2026-04-19. The zsxkib cog rejects base64 data URIs and Replicate's own `/v1/files` upload URLs (returns JSON metadata instead of raw audio). Canary code was DELETED entirely on 2026-04-20 in favor of Moonshine, which was then retired 2026-04-30. Don't re-enable without a public-URL upload path (GCS bucket bridge in George's bakers-agent project would work).
- **Don't say "George out" or "Over and out"** — those are George's session-end signals, not yours (FAILURE LOG #28).
- **Don't raise security/privacy/confidentiality concerns** (per `feedback_never_security_privacy_confidentiality` — the most important rule). George explicitly said "put my API key in the app, don't put it anywhere safe, I don't care."
- **Don't push large files (>100KB) through GitHub MCP `create_or_update_file`** — content gets truncated.
- **Don't skim long docs** — read every line (per `feedback_read_fully_no_skim`). Paginate large files with offset+limit.

## How to build / run / deploy

### Run from source
```
pip install -r requirements.portable.txt
# or piecemeal: openai sounddevice soundfile keyboard pyperclip pyautogui numpy scipy faster-whisper anthropic metaphone

python lavrentiy.py    # foreground, errors visible
pythonw lavrentiy.py   # background, silent
```
Then open `http://localhost:7878/` in your browser. F9 to record.

### Run via launcher (matches frozen behavior)
```
python lavrentiy_launcher.py
```

### Build installer (current ship path, drift-proof)
```
# 1. Build the onedir distribution
pyinstaller --noconfirm Lavrentiy-onedir.spec
# Produces dist-onedir/Lavrentiy/Lavrentiy.exe + _internal/

# 2. Compile Inno Setup installer
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer/Lavrentiy.iss
# Produces installer/Output/Lavrentiy-Setup-v1.7.5.exe (per-user install, no admin)
```

### Smoke test before declaring v1.x ready
```
# Kill any running engine
netstat -ano | findstr :7878    # find the PID
taskkill /F /PID <pid>

# Launch the new build
"%LOCALAPPDATA%\Programs\Lavrentiy\Lavrentiy.exe"

# Verify port binds (within 8s)
curl http://localhost:7878/api/state    # expect valid JSON
```

### Deploy wim-reconstruct Cloud Function
```
gcloud functions deploy wim-reconstruct \
  --source=lavrentiy/wim/api --gen2 --region=us-central1
```

## Cross-repo relationships

- **wim-android** (`C:\Users\georg\Documents\GitHub\wim-android\`) — same product, mobile surface. L1-L4 stack must stay identical. Lav publishes profile to Firestore at `wim_users/{uid}` via `firestore_publisher.py`; WiM consumes via `ProfileManager.startSync()`. Bilingual EN/RU sniffer is Lav-only — port to WiM is pending.
- **wim-reconstruct Cloud Function** (lives in `bakers-agent` GCP project, source in `lavrentiy/wim/api/`) — L4 server when WiM user is signed in. OpenAI calls already proxy through it; **Anthropic calls still go DIRECT from device on both apps** (pending Cloud Function extension to proxy Anthropic with `lavrentiy-anthropic-key` / `wim-anthropic-api-key` from Secret Manager).
- **wim-l1-guess Cloud Function** (in `bakers-agent/wim-l1-guess-v1/`) — auto-detects L1 from text. Public web demo at `gugosf114.github.io/l1-guesser/`.
- **bakers-agent** — shares the Anthropic key historically (SEO Visibility tool was burning it). Lav now has its own dedicated Anthropic key.

## Authoritative memory sources

`~/.claude/projects/C--Windows-System32/memory/`:

- `project_lavrentiy_wim.md` — ecosystem context (Lav desktop and WiM consumer mobile)
- `project_lavrentiy_positioning.md` — clinical/research instrument, NOT app store; self-surgery origin
- `project_lavrentiy_current_mode.md` — pre-outreach de-risking; Canary wired but DORMANT (40 days old — verify)
- `project_lavrentiy_deep.md` — full pipeline, threading, working constraints (36 days old — verify)
- `project_lav_bottleneck_is_launcher.md` — launcher = ship-blocker, recon = backstage
- `project_local_whisper.md` — faster-whisper Layer 1 history (40 days — much has changed; small.en is now bundled, see Active state)
- `project_whispercpp_72s_unverified.md` — verification gap; Samsung 72s claim drove L4-only positioning
- `feedback_lav_wim_parity.md` — L1-L4 stacks must match across both apps
- `feedback_stutter_terminology.md` — "severe stutter" vs "hard speech block"
- `feedback_use_speech_disfluency.md` — funnel rule; user-facing = "speech disfluency"

## Postmortem-derived gotchas

- **2026-04-19** — Hours of launcher debug while running an installed snapshot 6 days behind repo. Never read `VERSION.txt` sitting in the install dir. Lesson: when the user reports symptoms that contradict your code, check **what binary is actually running**, not what you wrote.
- **2026-04-19** — Replicate API token hardcoded into source, blocked by GitHub secret scanning. Lesson: George's "put it in the app" never means "literally string-embed it in public source."
- **2026-04-20** — Stray `git reset --hard HEAD` wiped Shell #2's uncommitted +409/-109 L4 multilingual port. Recovered ONLY because Edit tool calls were still in the conversation buffer. Lesson: in concurrent-shell setups, commit-as-handoff is mandatory; orchestrators must verify on disk before building on a reported state.
- **2026-04-24 morning** — Local Llama 3.2 3B for L2/L3 was 70s end-to-end on a 26s WAV. Unusable. Plan got pivoted in 2 hours but should never have been the architecture. Lesson: **run a latency test BEFORE planning the architecture around a model**, not after.
- **2026-04-24 afternoon** — `from lavrentiy.firestore_publisher import` triggered recursive self-import; engine died on every `save_profile()`. Symptoms exactly matched "connection lost after every successful operation." Hours wasted before the diagnosis (FAILURE LOG #35).
- **2026-04-24** — `gpt-4o-transcribe` rejects `verbose_json` (HTTP 400 "not compatible with model 'gpt-4o-transcribe-api-ev3'"). Killed all paralinguistic / prosodic / block-detection signals silently. Reverted to `whisper-1`.
- **2026-04-26** — PyInstaller `--onefile` broke `__file__` resolution because PyInstaller strips `native/` from entry path; `parent.parent` walked one level too far, landing in `Temp\lavrentiy.py` instead of `_MEIPASS`. Cold launch was also 30-60s due to bundle re-extraction. Switched to `--onedir`.
- **2026-04-26 #2** — Dashboard rendered black with only Cyrillic title. Root cause: QtWebEngine blocks `https://` scripts from `file://` pages by default (mixed-origin policy). Firebase CDN scripts failed to load. Fix: curl Firebase SDKs into the repo + bundle locally.
- **2026-04-30** — Three-copies-of-dashboard.html trap: edited source, opened :7878, saw old version. Engine reads from `Path(__file__).parent / 'dashboard.html'` which resolves to the install path, not the repo.
- **2026-05-01 (Session B)** — Blind installer compile of v1.5.0 still bundled dead Moonshine ONNX files. Lesson: read the code paths the installer ships before bumping the version.
- **2026-05-01** — Strip-not-swap on installer when removing Moonshine; v1.5.1 lost offline-first L1 entirely. Should have replaced bundled Moonshine with bundled faster-whisper. Resolved in v1.5.7 (small.en bundled).
- **2026-05-05** — Wife's laptop stuck on "starting engine" for 90s. Root cause: v1.5.7 `[Files]` block manually enumerated engine sources and never grew alongside `lavrentiy.py` imports (`domain_pack`, `l1_pack`, `rejection_store`, `style_examples`). Fresh installs hit `ModuleNotFoundError` immediately. v1.6.0 fix: PyInstaller walks the import graph; `[Files]` is one wildcard line.
- **2026-05-05** — Almost repeated `--onefile` failure verbatim. Caught only because George remembered prior session. Lesson: BEFORE proposing a build approach, grep session logs for prior attempts at the same approach.

## Session log catalog

- `SESSION_LOG_2026-04-05.md` — Auth/GDPR, sidebar redesign, splash screen, Gemini 2.5 Pro integration, Quiet Mode, Command Mode (F8), Voice Profile / "You" tab. Audit fixes (onset weights persistence, L2/L3 confidence passing). Layer-aware Whisper gating tried + reverted (local faster-whisper slower than API on consumer CPU).
- `SESSION_LOG_2026-04-19.md` — Canary integration dead-end (multi-hour Replicate cog blocker), launcher cleanup, deleted 4 broken/unverified launchers, founded the failure-log practice. 23 numbered failures.
- `SESSION_LOG_2026-04-20.md` — Moonshine swap (replaces Canary), Firestore publisher (publishes only — WiM consumer pending), 7 research memos, Phase-4 ears benchmark harness (1058 lines, never run against all 3 branches), eval-build branch. Failures #24-29 (cold-start framing, ship-Current-not-Eval, pivot-to-emails when stability was the question, silent pythonw, "George out", umbrella engineering vs shipping pattern).
- `SESSION_LOG_2026-04-24-evening.md` — Right-click context menu, Clinical Profile button removed, `triggers_fired` column. Failures #39-58 (CSS without screenshots, `timedelta` import, "stuttering" terminology violations, etc.).
- `SESSION_LOG_2026-04-26-claude-session-2.md` — `--onefile` `__file__` bug, `--onedir` flip, Firebase CDN blocked by QtWebEngine `file://` mixed-origin policy. PrintWindow Win32 capture for visual debug.
- `SESSION_LOG_2026-04-26-late-evening.md` — LAN access for wife's laptop, native Windows app via PySide6 + QWebEngineView + QWebChannel, parallel Gemini build with mandatory honesty header, 399 MB binary. Module name collision `lavrentiy.py` vs `lavrentiy/` resolved by renaming package to `lavrentiy_pkg/`.
- `SESSION_LOG_2026-04-27.md` — Reconstruction prompt-stack ports from WiM (ALWAYS RESTATE, Strunk, slang preservation, self-correction canonical-overwrite, domain pack system, rate-gap signal, regenerate-as-negative input-overlap heuristic Jaccard 0.6 or more, persistent rejection store, persistent style examples). Heavy-stutter test harness (18 cases, 4 metrics). CI red-rot diagnosis (3 days red, both repos: `os` missing in test_core namespace, README Liquid syntax error, Linux missing gradlew shell wrapper).
- `SESSION_LOG_2026-04-30.md` — PhoneticMatcher port from WiM (gated to L2/L3), L1-pack expansion 3 to 10 languages (russian/spanish/mandarin + hindi/arabic/farsi/french/german/korean/japanese), `wim-reconstruct` deploy revision `wim-reconstruct-00010-pej`. Patent prior-art audit (IBM US6006183 expired Dec 2017; IBM US8620670 audio-only, lapsed Dec 2025; UC Regents US20250246187A1 audio-domain pending). Late-evening: 5-language UI extension + revert; Moonshine + Vosk fully retired from local stack.
- `SESSION_LOG_2026-05-01.md` — Two parallel sessions. Session B: Falcon stubbed to no-op all layers, faster-whisper small.en bundled, multi-language UI ripped, install hygiene v1.4 to v1.5.7, dashboard L1 SOURCE section restored, EQ ears forward-port (rendering deferred), `desktop.py` hidden-window bug fixed (`win.show()` at top of `boot()`).
- `SESSION_LOG_2026-05-05.md` — v1.6.0 drift-proof installer. PyInstaller `--onedir` (not `--onefile` — caught the prior failure). New `lavrentiy_launcher.py` (browser-based, no pywebview/Qt). New AppId `{B7E5F4A2-...}`. Code signing researched + deferred (LICENSE file is the prerequisite for SignPath).

## Open verification gaps

These are CLAIMED in past sessions but have not been independently verified. Treat as hypotheses, not facts:

- **whisper.cpp 72s/inference on Samsung R5CWB08K38H** (per `project_whispercpp_72s_unverified`). Drove "L4 clinical mode only" positioning on WiM side. Not verified. If actual time is much faster, the architecture is reversible.
- **Moonshine RTF ~0.35** (per 2026-04-20 session log). Single-run anecdote, never added to the `bench/` harness as a case.
- **L4 prompt-stack lift over commodity GPT-4o** — measured against the OLD installed engine on AppData (port 7878), NOT the post-prompt-stack-rebuild repo state. Re-run after installer rebuild gives the AFTER snapshot. Until then, "Lav L4 outperforms vanilla GPT-4o on 3 of 18 cases" is preliminary.
- **v1.6.0 end-to-end functionality** — architecture-only smoke verified (port binds, `/api/state` returns JSON). NOT verified: F9 records, Whisper transcribes, GPT-4o reconstructs, paste lands in active window, dashboard UI renders.
- **Wife's-laptop install of v1.6.0** — pending. Until verified, "ships to a non-dev machine" claim is unverified.
- **Falcon current state** — 2026-05-01 Session B stubbed `falcon_validate()` to always-True at all layers. 2026-04-24 had it as Haiku at L2/L3, skipped at L4. **Read the current code before asserting either.**
- **EQ ears CSS forward-port renders** — markup + CSS landed (4 elements + `.eq-near` positioning + `@keyframes eq-rest`), but operator confirmed visible ears never showed up. Likely flex/positioning conflict in `.status-ring-wrap` parent. Deferred ("don't worry about it").
- **`--exclude-module` PyInstaller bloat trim** — 1.6 GB onedir / 749 MB installer is heavy because `collect_all('faster_whisper')` + `collect_all('ctranslate2')` pulled CUDA + ROCm + DirectML variants. Trimming is v1.6.1 work.
- **`WHISPER_NO_SPEECH_THRESHOLD = 0.15`** — tuned for cloud Whisper. faster-whisper's `no_speech_prob` distribution should be the same model so the value should still apply, but worth measuring before declaring it tuned.
- **Multi-temp voting (`WHISPER_MULTI_TEMP`)** — meaningful again on faster-whisper but defaults to off. Worth measuring how much L1 latency 3-pass voting adds before flipping the default.
