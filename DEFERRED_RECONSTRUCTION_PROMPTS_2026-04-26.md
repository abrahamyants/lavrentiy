# Reconstruction Build Status — 2026-04-26 session

This file was originally a list of 5 deferred features. After the Rambo
build pass, **3 of the 5 are now in code** and **2 are still deferred**.
Standing rule: **nothing committed or pushed yet** — coordinate with
George before any git history operations (other Claude sessions may have
uncommitted work in same repos).

---

## ✅ DONE in this session (uncommitted, repo-only)

### Earlier — initial ports

- **Lav: ALWAYS RESTATE + Strunk + slang preservation block** → `lavrentiy.py` L2/L3 conditional
- **Lav: Self-correction canonical-overwrite rule** (handles "I mean / actually / no wait / scratch that")
- **Lav: Domain pack system** → `domain_pack.py` + `domain_packs/{sf_pro,legal,medical,finance,hipaa}.json` + injection wired
- **Lav: `'I mean'` removed from discourse-marker drop list** (handed to self-correction rule)
- **WiM: Self-correction rule** → `ReconstructClient.kt`
- **WiM: `'I mean'` fix** (parity with Lav)

### Big-build pass

- **#1 Rate-gap signal injection (both apps)**
  - Lav: new `audio_duration_s` + `word_count` params on `reconstruct()` and `reconstruct_via_backend()`. Note appended to `aggression_note` when wps < 1.5 (compression — blocks/silences/extended pauses) or > 4.0 (cluttered/rushed). Computed at `pipeline()` from `audio_data` + `raw_text.split()`.
  - WiM: new `compressionRatioNote: String` param on `ReconstructClient.reconstruct()`. Pre-formatted by `BubbleService` from existing `RateGapDetector.Result` (which was already computed but only used to bump `speechSeverityMod`). Now also surfaces the ACTUAL numbers (wps, baseline, ratio %) to the model — two channels of the same signal, both useful.
- **#2 Lav: regenerate-as-negative-example port**
  - New `previous_outputs` param on `reconstruct()` and `reconstruct_via_backend()`.
  - Prompt block ports WiM `ReconstructClient.kt:425-432` verbatim ("speaker is asking for a DIFFERENT phrasing / produce a new reconstruction with different word choices, sentence structure, rhythm").
  - **Critical design decision:** Lav has no explicit "regenerate" button (unlike WiM's IME). Implemented input-overlap heuristic (`_detect_input_overlap_redo`) — Jaccard similarity ≥ 0.6 between current and prior raw_text → treat as regenerate. Soft signal vs WiM's hard button-press signal. Threshold tunable via `_REGEN_OVERLAP_THRESHOLD`.
  - Buffer: `_recent_outputs` (last 4 successful reconstructions). `_record_reconstruction_for_redo()` updates after each successful pipeline pass.
- **#3 Big Swing #2 — Audience-Specific Reconstruction (WiM v1)**
  - **Patent claim line:** "Voice transcription post-processor that conditions reconstruction style on real-time foreground-app + IME-field metadata."
  - New file: `AudienceContext.kt` — package-name → `Profile(category, audience, mediumExpectations)` mapping for 13 specific apps (Gmail, Outlook, Slack, Teams, LinkedIn, SMS variants, WhatsApp, Telegram, FB Messenger, Instagram, Snapchat, Discord, Reddit, Docs/Sheets, Notion, Asana/Trello/Jira) plus category fallbacks. Formats READER block for prompt.
  - `WimAccessibilityService` exposes `currentForegroundPackage` (set in `TYPE_WINDOW_STATE_CHANGED` event, alongside existing `autoSwitchTone`). Cost: zero new permissions, infrastructure already existed.
  - `ReconstructClient` accepts `audiencePackage: String?`, appends `AudienceContext.formatReaderBlock(audiencePackage)` after `precedingContext` block in the system prompt. Backend payload also forwards it (`audience_package` key, ignored gracefully if backend doesn't yet read it).
  - `BubbleService` passes `audiencePackage = WimAccessibilityService.currentForegroundPackage` at the main reconstruction call site.
  - **Patent action items:**
    - Search prior art on Google Patents + USPTO PPUBS: "voice dictation context-aware reconstruction", "IME metadata reconstruction", "foreground-app-conditioned speech post-processing"
    - Provisional patent claim block — George can file directly ($130 micro-entity fee, Patent Center)
    - The filing receipt itself is the asset; "patent pending" goes on slides regardless of grant outcome

### Test status

- Lav: `python -m py_compile lavrentiy.py` ✅ + `python -m py_compile domain_pack.py` ✅ + `domain_pack.load_pack('sf_pro')` returns 146 vocab + 66 phonetic aliases ✅
- WiM: `gradle assembleDebug` exit 0 across all 3 build runs (initial parity port → rate-gap port → audience-context port) ✅
- WiM install: SKIPPED in all build runs because no Android device connected to adb. APK at `app/build/outputs/apk/debug/app-debug.apk` ready for `adb install` when a device is plugged in.
- Live engine (running install at `AppData/.../Lavrentiy-Eval/engine/`): UNCHANGED. All Lav code edits are repo-only and activate on next installer build.

---

## ⏭️ STILL DEFERRED (need infra not in current scope)

### #4 — Positive in-context few-shot from edit history (both apps)

**Why still deferred:** Needs edit-detection infrastructure. Hard in WiM (Accessibility doesn't easily expose user-typed-after-paste). Easier in Lav (clipboard-based; can poll for divergence).

**Goal:** When the user EDITS WiM/Lav's output after reconstruction, capture the edit as a (raw_input, model_output, user_final) triple. Inject the last 3-5 such triples into the next reconstruction's prompt as positive few-shot examples. The model learns the user's voice over time.

**Files to touch:**
- New module `EditHistory` storing N most recent triples in encrypted local storage (DataStore in WiM, JSON file in Lav)
- WiM: `WimAccessibilityService` after pasting reconstruction, watch the field for K seconds; if it changes, save (raw, output, final) triple
- Lav: clipboard polling — same idea, watch clipboard for divergence after reconstruction
- Both: `ReconstructClient.kt` / `lavrentiy.py reconstruct()` — read EditHistory, append last 3-5 triples as few-shot block in L3+ only (L2 stays minimal)

**Sample injection:**
```
RECENT USER PREFERENCES (this user has previously preferred these reconstructions):
1. Raw: "[...]" → Final: "[...]"
2. Raw: "[...]" → Final: "[...]"
Apply the same style choices when relevant.
```

**Privacy:** All on-device. Cap history at N=20 (~20KB). Profile screen needs an "Erase voice memory" button.

**Acceptance:** Daisy uses WiM for a week. Reconstruction quality on her professional vocabulary improves measurably (qualitative — A/B side-by-side after 50 reconstructions).

**Estimate: 4-6 hours per app once infra exists.**

### #5 — Proactive negative few-shot from cross-session rejection history (both apps)

**Why still deferred:** Lav already has same-session regenerate-as-negative (delivered above). What's still missing: PERSISTENT storage of regenerate failures across sessions, with proactive injection on future reconstructions.

**Goal:** When the user hits redo, persist the rejected output. On the NEXT reconstruction (any time later), if the new context resembles the rejected one, preemptively inject "the user has rejected this style of phrasing in the past — avoid it."

**Files to touch:**
- Both apps: `RejectionStore` module storing rejected outputs with simple keyword fingerprints (no need for vector DB at this scale)
- Both apps: at reconstruction time, fingerprint the raw input, look up nearest rejections, inject as negative few-shot if similarity threshold met
- Both apps: Profile screen — "Erase rejection history" button

**Trade-off:** Adds latency (lookup) and complexity (fingerprinting). Start with the simpler version: keep last 10 rejections, always inject all 10 as "patterns you've rejected before — do not repeat" without similarity matching. Test if simpler version moves the needle before building the smart one.

**Acceptance:** User has rejected "circle back" 3 times in past month. Reconstruction at any layer no longer produces "circle back" without explicit user usage.

**Estimate: 3-4 hours starting with the simple version.**

---

## Recommended next session order

1. **#5 simple version (10 most recent rejections, no similarity)** — closest to existing infra (Lav has `_recent_outputs` already; just need persistence). Highest signal-to-effort.
2. **#5 smart version (with fingerprinting)** — only if simple version doesn't move the needle.
3. **#4 positive few-shot** — biggest infra build (edit detection); save for last.

Total deferred work: ~7-10 hours.

## Standing rules carried out of this session

- **No `git commit` or `git push`** without George's explicit greenlight. Other Claude sessions may have uncommitted work in same repos. (Memory: `feedback_no_commit_push_without_check.md`)
- **Lav code changes are repo-only** until next installer build. Running engine in `AppData/.../engine/` is untouched.
