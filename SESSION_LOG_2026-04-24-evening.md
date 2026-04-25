# SESSION LOG 2026-04-24 (evening continuation)

Continuation of the same Claude Code session that produced the four
commits earlier today (`69dc5e2` → `f009516`). Captures the late-evening
UX cleanup work that wasn't committed to the README.

## What landed

### Right-click context menu (custom)
- pywebview/WebView2 suppresses the native browser context menu, so Ctrl+C
  worked but right-click did nothing on selected text in the dashboard.
- Added a custom JS context menu (`#ctx-menu`) with Copy / Select All /
  Paste, triggered on `contextmenu` events inside `.tab-panel`. Uses
  `navigator.clipboard.writeText()` for copy and falls back to
  `document.execCommand('copy')` if the clipboard API isn't available.
- Esc and any outside click dismiss the menu. Item is auto-disabled when
  no selection exists (Copy greys out until you highlight text).
- CSS uses the dashboard's existing copper/bronze accent palette so the
  menu feels native to the app.

### Clinical Profile button removed
- The 🩺 CLINICAL PROFILE button in the Learning tab generated a
  zero-filled raw-aggregation report (per-trigger event counts always 0
  because session-level event tagging didn't exist).
- Redundant with the Weekly Report (📊 GPT-4o narrative summary) which
  shows real numbers via cumulative profile state.
- Removed the button. Weekly Report stays as the canonical clinical view.

### Session-level trigger event logging
- Added `triggers_fired` column to the sessions SQLite table (auto-migrated
  via existing ALTER TABLE block).
- `log_session()` now scans the raw transcript for occurrences of the
  user's profile trigger words and stores the matched list as JSON in the
  new column. Lightweight: case-insensitive substring scan, no API call.
- This unblocks per-trigger event counts in the Weekly Report and any
  future analytics that aggregate "how often did trigger X fire this
  week" — previously not computable because sessions didn't tag triggers.
- Latency impact: zero. Just a few extra bytes on a DB write that was
  already happening per session.

### Toggle-disabled CSS made generic
- Earlier in the day I added `.toggle-disabled` scoped only to
  `.toggle-row`. When the WHISPER panel needed the same treatment
  (`engine-section-card`), the class didn't apply. Promoted the rule to
  a generic `.toggle-disabled { opacity: 0.35; pointer-events: none }`
  that works on any element.
- Now the WHISPER diagnostic panel correctly greys out at L1/L2/L3.

### Other minor

- L1 hint label corrected: "Whisper only" → "Moonshine local" (the
  language-pack `tab_profile.en` field had also been overwriting "Profile"
  back to "The File" on every state poll — fixed by updating the
  translation map directly).
- WHISPER panel + paralinguistic + prosodic toggles all share the same
  L4-only grey-out treatment + tooltip "Layer 4 only — needs Whisper
  segment data."
- F5 / Ctrl+R wired explicitly via JS `keydown` listener (pywebview
  swallows the default), with a "F5 or Ctrl+R to refresh dashboard" hint
  in the rotating cmd-hint pool.

## Pending (carry-forward)

1. **Consolidate Weekly Report + Insights tab.** Currently:
   - Insights tab: tile view of fluency analytics (FLUENCY TREND, AVG PAUSE,
     etc.) — gated to L4
   - Learning tab: 📊 WEEKLY REPORT button generates GPT-4o narrative
   - Both use the same underlying data, different presentation
   - Should fold the Weekly Report INTO the Insights tab so there's one
     home for clinical analytics, not two.
2. **Profile-loading-without-sign-in fix.** Engine boots into whichever
   profile was last active, leaks data across users on shared machines.
   Plan written + paste-prompt provided earlier in the conversation. Not
   yet executed.
3. **Mirror sidebar prune to wim-android.** Drop "stuttering" terminology
   throughout, rename layers to Transcription / Reconstruction / Speech
   Disfluency, change bubble UI from transparent overlay to cloud-bubble
   shape. Message drafted; needs a working `claude` shell after the
   `--resume` CLI bug is sorted.

## Failure log additions

### #39 — pasted "REFRESH" button into the sidebar instead of just removing it (2026-04-24 evening)

George said "remove" the visible REFRESH button from the top bar and
"include in the rotating hints" the F5/Ctrl+R info. I interpreted it as
"move it to the sidebar" and inserted a sidebar button. He clarified
sharply: *"remove it, re-work it. I don't want to see it. Just include in
the instructions we have."* The hint-pool addition was the actual ask;
the sidebar button was unwanted scope I added by misreading "remove +
mention" as "relocate + mention."

Pattern: when a user gives a two-part instruction ("remove X, add Y to
hints"), execute both literally. Don't synthesize a third option that
combines them.

### #40 — recommended a feature without empirically checking the dependency (2026-04-24 evening)

When George asked about adding a Falcon-style check at L1, I described
"Haiku reads Moonshine output and flags suspicious-looking text" as if
flagging would be the action. He pushed back: *"flag for who? you?"* —
correctly pointing out that a flag with no actor is useless. I'd
described the diagnostic without describing the consequence; reframed to
"Haiku FIXES errors it sees, output is the corrected version."

Pattern: when proposing a feature, describe the FULL chain — what the
component reads, what it does with what it sees, what the user-visible
output is. Don't stop at "checks" or "validates" without naming the
correction action.

### #41 — `timedelta` used without import, took down the engine for ~10 minutes of George's debugging time (2026-04-24 evening)

The engine seized while George was testing the L1 Haiku polish. Pattern
was a long Processing... with no completion. Eventually surfaced via
`engine_err.log`: `NameError: name 'timedelta' is not defined`. The
streak-calculation code at line ~7116 used `timedelta(days=1)` but only
`from datetime import datetime` was imported (not timedelta). Existed
in the codebase before this session — got triggered by the dashboard
polling the streak/insights endpoint while another request was hung,
which jammed the HTTP server thread pool.

Pattern: pre-existing bugs in unfamiliar code paths get exposed by new
features that touch adjacent code. Always check `engine_err.log` first
when "feels stuck" reports come in — most silent hangs in this codebase
have left a captured traceback since I added the stderr capture this
afternoon.

### #42 — overestimated implementation time as "2-3 hours" for what took ~10 minutes (2026-04-24 evening)

George called this out directly: *"how much you wanna bet that your 2-3
hours is under 5 minutes?"* The Profile overlay implementation
(originally proposed) was actually 7 minutes of wall-clock work. The
2-3 hour estimate was anchored to human-developer time, not Claude-tool
time.

The memory rule already exists (`feedback_dont_overestimate_time.md`).
This is a sustained violation, not a fresh failure.

Pattern recognized: when estimating, default to Claude-time (Edit calls
are seconds, not hours) and ignore the training-data anchor of human dev
estimates. If unsure, skip the estimate entirely rather than padding.

## Engine state at log time

- Window PID 5652, engine PID 15868, layer 1, casual tone
- Schema: 18 columns including new `triggers_fired`
- Right-click context menu live on all tab panels
- Auth: not signed in, gugosf profile loaded (the data leak issue
  documented in pending #2)

## Files modified this evening

- `dashboard.html` — right-click menu CSS + DOM + JS, Clinical Profile
  button removed, generic `.toggle-disabled`, several small label fixes
- `lavrentiy.py` — `triggers_fired` column + INSERT, `timedelta` import
  fix, `_seedProfileTabExtras` for Profile tab WiM-mirror sections,
  L1 Haiku polish path, `_kill_engine_on_port` replacing `_kill_stale_pythonw`
- `local/asr_local.py` (gitignored) — empty-text result returns gracefully
  instead of cascading retry

## What the next session should do first

1. Read this file + the README's 2026-04-24 entries.
2. Pick up the consolidation work (Weekly Report → Insights tab).
3. Execute the profile-loading-without-sign-in fix (paste-prompt is in
   the earlier conversation).
4. Once `claude --resume` works again, paste the WiM-android sidebar
   rename + bubble-shape message to the parallel session.
