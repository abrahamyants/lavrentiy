# Session log — April 27, 2026 — Reconstruction prompt-stack + heavy-stutter test infrastructure + CI red-rot diagnosis

This session ran from late evening 2026-04-26 through early 2026-04-27 UTC. Three threads, sequenced: (1) port WiM's L2/L3 reconstruction improvements to Lav and add new ones (rate-gap, regenerate-as-negative, persistent rejection / style stores); (2) build a heavy-stutter test harness with a commodity GPT-4o baseline; (3) discover and fix three CI failures that had been red for ~3 days across both repos.

## Thread 1 — Reconstruction prompt-stack (lavrentiy.py)

Goal: close the WiM↔Lav L1-L4 parity gap and add new features. WiM had already shipped four reconstruction features (ALWAYS RESTATE + Strunk rules, slang preservation, domain packs, regenerate-as-negative-example). None were in Lav. Plus three new features were brainstormed in this session: rate-gap signal injection, persistent rejection store (cross-session negative few-shot), and persistent style-examples store (positive few-shot via implicit acceptance).

### ALWAYS RESTATE + Strunk rules + slang preservation

Ported from WiM `ReconstructClient.kt:267-285` to Lav `lavrentiy.py:2870` — the L2/L3 conditional in `reconstruct()`. The block:

- "ALWAYS RESTATE — DO NOT RETURN INPUT UNCHANGED."
- Strunk & White rules (omit needless words, active voice, definite/specific/concrete language, sentence length 15-20 words)
- Federal Plain Language Guidelines (simple/active/affirmative/declarative, drop discourse markers)
- Stream-of-consciousness reorder license: the speaker is brain-dumping, model RESTRUCTURES into context→ask→close (email) / setup→question→specifics (message)
- Slang preservation: rizz/bussin/no cap/mid/delulu/skibidi/ick/fanum tax preserved as INTENTIONAL not transcription error

### Self-correction canonical-overwrite

New rule (also added in WiM same session by another agent):

> When the speaker uses 'I mean', 'actually', 'no wait', 'scratch that', 'let me rephrase' — treat what FOLLOWS as canonical and DISCARD what came before. This is intentional self-correction, not disfluency.

Crucial for stutterers (covert revision is core stuttering behavior). Note: 'I mean' was REMOVED from the discourse-marker drop list in the same edit, otherwise the two rules conflict.

### Domain pack system

New `domain_pack.py` at repo root + `domain_packs/{sf_pro,legal,medical,finance,hipaa}.json`. Mirrors WiM's DomainPackHelper. Activated by `profile_industry` pref (existing — same source of truth as WiM). Injection point: `reconstruct()` L2/L3 conditional, after L1 pack. Format: prose hint + canonical vocab list + phonetic-alias table (e.g. "mom" → "MoM", "evita" → "EBITDA", "voir deer" → "voir dire").

### Rate-gap signal

Added `audio_duration_s` and `word_count` params to `reconstruct()` and `reconstruct_via_backend()`. In `reconstruct()` body, when wps < 1.5 (compression — silence/blocks/extended pauses) or > 4.0 (cluttered/rushed), appends a rate-gap note to `aggression_note`. Computed in `pipeline()` from `audio_data` + `raw_text.split()`.

### Regenerate-as-negative-example

New `previous_outputs` param. Prompt block ports WiM `ReconstructClient.kt:425-432` verbatim. Critical design difference: WiM has an explicit IME regenerate button → hard signal. Lav has no equivalent button, so used input-overlap heuristic — Jaccard similarity ≥ 0.6 between current and prior raw_text → treat as regenerate. Soft signal vs WiM's hard signal. `_recent_outputs` deque stores last 4 successful reconstructions; `_record_reconstruction_for_redo()` updates after each successful pipeline pass.

### Persistent rejection store

New `rejection_store.py` mirroring WiM's `RejectionStore.kt`. JSON file at `<repo>/rejection_history.json`, capped at 30, dedupes against most recent. Atomic `.tmp+rename` write to survive engine crashes mid-save. Capture point inside `reconstruct()` itself (when `previous_outputs` is non-empty, last entry is being rejected — record it). L3+ injection block: "PERSISTENT REJECTION HISTORY (recent reconstructions this user rejected — DO NOT echo back, use only to avoid producing structurally similar text)".

### Persistent style examples (positive few-shot via implicit acceptance)

New `style_examples.py` mirroring WiM's `StyleExamples.kt`. State machine handled in `pipeline()` (verdict at entry — if regenerate, drop pending pair; if fresh dictation, promote pending pair to accepted) and `reconstruct()` (L3+ prompt block). False-negative case: last reconstruction of a session never gets verdict'd (no next call to promote it) — acceptable cost; v2 can persist on exit.

## Thread 2 — Heavy-stutter test harness

Goal: build an automated test corpus + scoring harness for heavy-block reconstruction quality. The strategic blocker for foundation outreach (per memory `project_lavrentiy_current_mode`).

### Background agent: corpus research + scaffold

Spawned an Opus 4.7 background agent with explicit deliverables. Output:

- `HEAVY_STUTTER_CORPUS_RESEARCH.md` — 5 corpora characterized from primary sources (SEP-28k, FluencyBank Timestamped, KSoF, UCLASS, LibriStutter). Key finding: no public English block-annotated corpus exists with usable inter-annotator agreement. SEP-28k labels blocks but Fleiss kappa = 0.25.
- `heavy_stutter_test_scripts.json` — 18 hand-designed cases covering silent blocks, phantom-word hallucinations, mid-word abandonment, covert revision via "I mean" / "actually", phone/presentation/email/medical/legal/casual scenarios.
- `test_heavy_stutter.py` — harness with module + HTTP backends, scores WER + Intent-Jaccard + Coverage + Proper-noun preservation.
- `HEAVY_STUTTER_ACCEPTANCE_CRITERIA.md` — quantitative bar (L4 WER ≤ 0.30, Intent Jaccard ≥ 0.70, Coverage ≥ 0.85, Proper-noun ≥ 0.90).

### First run + caveat surfacing

First `--backend=http` run: 18 cases × 4 layers = 72 reconstructions, 123.3s wall clock. L4 hit perfect scores on 12 of 18 cases; 3 cases struggled (h07 phone-stress avalanche, h12 doctor question, h18 block-then-substitution).

**Two caveats surfaced before pitch use:**
1. Test corpus used literal `[BLOCK]` tokens — Whisper would never emit these. Real silent-block ASR output is either dropped silence OR hallucination phrases ("thank you for watching", "subscribe", "thanks for watching"). The corpus needed revision.
2. Commodity GPT-4o baseline missing. Without it, can't measure Lav's lift over a $0.01 vanilla call. Per memory `feedback_name_commodity_baseline.md`.

### Corpus revision + commodity baseline addition

Revised 11 of 18 cases — replaced `[BLOCK]` tokens with realistic Whisper output (mix of dropped silence and documented hallucinations like "thank you for watching"). Added commodity-baseline path to harness: vanilla GPT-4o call with one-line system prompt, scored alongside Lav L1-L4. API key fallback walks env var → repo root → wim/api → engine → install dir, with a probe call (`client.models.list()`) to skip stale keys.

### Re-run with revised corpus + commodity column

Headline: **Lav L4 distinctly outperforms vanilla GPT-4o on 3 of 18 cases** (h01, h03, h09 — Whisper-hallucination contamination). **Matches on 14 cases.** **Commodity wins h07 by 0.17 WER.** Net: prompt-stack value concentrates in hallucination-cleanup, not clean-disfluency cleanup.

Important caveat captured at the time: this measures the OLD installed engine on AppData (port 7878), not the post-prompt-stack-rebuild repo state. Once installer rebuilds with new code, re-run gives the AFTER snapshot. Did not push for a foundation pitch — this is engineering self-knowledge, not pitch material. Per the saved memory `project_lav_bottleneck_is_launcher.md`.

## Thread 3 — CI red-rot diagnosis (both repos, 3 days red)

George asked for a happy-or-sad read on the commit history. Surface answer: commit hygiene excellent (atomic, conventional-style, narrative-clean — bubble unified build numbers phases 0-7). CI broken on every push for ~3 days, nobody looking. My 3 commits today joined the failed pile.

### Lav CI — `Tests` workflow

**Failure mode:** environment mismatch.
**Root cause:** `test_core.py:22` does `exec(const_block, ns)` where `const_block` is the `LANGUAGE..._personal_onset_weights_by_lang` range from `lavrentiy.py` (lines 182-975). That range now contains `os.environ.get(...)` at lines 217-220 (LOCAL_FW_MODEL_SIZE etc., added when faster-whisper config landed). The test's `ns` dict didn't include `os` → `NameError: name 'os' is not defined`. Test crashed during setup, ran zero assertions.
**Fix:** commit `581fdc4` — added `import os` and `'os': os` to namespace. Verified locally: 39 of 39 tests pass.

### Lav CI — `pages-build-deployment` workflow

**Failure mode:** content typo manifesting as Liquid syntax error.
**Root cause:** `README.md:1865` had `` `&#123;%USERPROFILE}\.cache\moonshine\base\` ``. Jekyll's Liquid parser saw `&#123;%` as an unterminated tag opener. Pages build crashed with `Liquid syntax error (line 1865): Tag '&#123;%' was not properly terminated`. Bonus: `&#123;%USERPROFILE}` is also a real Windows env-var typo — should be `%USERPROFILE%` (percent on both sides, no braces).
**Fix:** commit `c12c01f` — single-character fix. Both Liquid AND content correctness resolved.

### WiM CI — `Build & Test` workflow (cross-repo finding)

**Failure mode:** environment mismatch — committed in `wim-android` repo but discovered while diagnosing Lav.
**Root cause:** Linux runner can't execute `./gradlew assembleDebug`. The Unix gradlew shell wrapper was never committed (only `gradlew.bat` is tracked; `gradle/wrapper/{jar,properties}` exist). Windows git-bash falls back to `.bat` invisibly; Linux doesn't.
**Fix:** WiM commit `e52c6c9` — replaced `./gradlew` with `gradle/actions/setup-gradle@v4` + plain `gradle` invocation, pinned to gradle 8.11.1 (matches `gradle-wrapper.properties`).

## Discoveries / unknown unknowns

### Concurrent-session work duplication

Mid-session, ran `git log --oneline -10` and discovered a parallel agent had ALREADY committed the exact features I was building: `feat(domain-pack)` `feat(rejection-store)` `feat(style-examples)` `feat(audience-context)` (WiM). My `Write` tool calls had silently produced identical content — `git status` showed no modifications for those files because my output matched HEAD byte-for-byte. The architecture port from WiM was straightforward enough that two agents, given the same inputs and conventions, converged on the same output.

Real conflict points: `lavrentiy.py`, `ReconstructClient.kt`, `WimAccessibilityService.kt` had edits from BOTH me AND another session interleaved. No git-level conflict markers, just stacked uncommitted state.

### WiM linked worktrees

`git branch -a` in wim-android shows `+` prefix on `claude/great-chaplygin`, `claude/practical-golick`, `claude/stoic-jones`, `feat/l4-prompt-rewrite`, `feat/wearos-companion`, `merge/vosk-into-main` — those branches are checked out in **linked worktrees**. Multiple working directories of the same WiM repo on disk simultaneously. Other Claude sessions are editing parallel filesystems I can't see from `Documents/GitHub/wim-android/`.

### CI nobody-checking pattern

10 of 10 latest CI runs failed in BOTH repos. Same errors repeating, not a regression cascade. The pattern: someone wrote thorough CI, then nobody looked at it, and content/code drifted past what the workflows test. Three days of red without a single "wait, is CI broken?" question. The commit-hygiene quality and the CI-rot quality are wildly inconsistent — same author can't have written both.

## Commits landed (Lav)

In session order:
- `c6d8b17 feat(lavrentiy): self-correction + always-restate + integrations for domain/style/rejection` — +301 lines into `lavrentiy.py`
- `f97668e test(heavy-stutter): corpus revision + commodity baseline` — corpus + harness
- `4b2d6ef test(heavy-stutter): additional run results 02:38 + 02:42` — 4 result files
- `6d21014 feat(wim/api): L1-pack injection wiring for Cloud Function reconstruct` — another session's L1-pack work that landed during my push
- `581fdc4 fix(ci): add os to test_core namespace dict for exec'd constants block`
- `c12c01f fix(ci): correct &#123;%USERPROFILE} typo in README, unblocks Pages Liquid build`

## Memories saved this session

- `feedback_no_commit_push_without_check.md` — concurrent sessions in same repos; commit/push are explicit approval gates
- `feedback_max_pro_x20_no_token_concerns.md` — George is on Max Pro x20; stop adding cost caveats; sub-agents are default tooling
- `project_lav_bottleneck_is_launcher.md` — Lav's ship-blocker is launcher / install UX, not reconstruction quality. Recon work is backstage tweaks, not pitch material.

## Open at session end

- 3 fix commits in this repo NOT pushed yet (orchestrator handles push approval)
- Lav installer rebuild deferred — running engine in `AppData/.../engine/` is unchanged, my Lav code is repo-only and activates on next installer build
- The wim/api/reconstruct.py L1-pack wiring landed as `6d21014` while I was working — properly isolated from my commits per the original triage
- Heavy-stutter harness committed but only run against OLD engine; AFTER snapshot waits for installer rebuild
