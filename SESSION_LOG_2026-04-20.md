# Lavrentiy — Session Log 2026-04-20

**Same session as `wim-android/SESSION_LOG_2026-04-20.md`** — this half documents the desktop / research / cross-project work. Both files are insurance against session death; read whichever repo you land in first.

---

## READ FIRST — terminology rule

George's saved memory rule (`feedback_use_speech_disfluency.md`):
- **User-facing copy:** "speech disfluency", NOT "stuttering".
- **Research memos citing academic lit** (this repo's `docs/*.md`): "stuttering" is fine — it's the technical term in the field. Keep citations accurate.
- **Code identifiers:** keep existing names (`STUTTER_FRAGMENT` regex, etc.) — changing them has no marketing value and risks bugs.

WiM-side Play Store copy currently violates this rule. See `wim-android/SESSION_LOG_2026-04-20.md` for that punch list.

---

## What shipped today (Lavrentiy) — 11 commits

```
fa00cd1 Add foundation grant landscape research memo
de9a6a8 Add YOLO-Stutter memo; use Moonshine fallback
68303a6 Add L4 prompt engineering memo
777fd28 Firestore publisher: cross-device profile sync from desktop to WiM
375fcf9 Add clinical validation protocol memo
9bc8803 Add multilingual pack, research memos, benchmark harness
310d4dc README: 2026-04-20 changelog entry + FAILURE LOG 24-29
c096733 Add phase2/phase3 evaluation scripts & matrices
2690981 Remove _eval_strip_test.py — one-shot verification harness
abb28f2 eval-build v1.2.1: add 4 more fixes (8 total)
be07f7b Add eval-build branch for institutional outreach
```

## Major changes in detail

### 1. Moonshine swap (replaces Canary)

`whisper_local.py` rewritten for Useful Sensors Moonshine (ONNX). Measured RTF 0.35 on desktop — roughly 3× faster than Canary-Qwen-2.5B real-time. Python 3.14-alpha has an `httpx` bug that breaks `huggingface_hub` model downloads; worked around by using stdlib `urllib` directly in the download path.

`lavrentiy.py` — Canary code deleted, Moonshine hooked in as primary. Fallback chain: Moonshine → OpenAI Whisper API → local faster-whisper. `CANARY_ENABLED` flag removed entirely.

`whisper_local.py` is gitignored, so the rewrite does NOT show in `git diff`. Do not be confused by its absence from the commit list.

### 2. Firestore publisher

`firestore_publisher.py` — desktop-side component that publishes the user's learned profile to Firestore for WiM to consume:
- `trigger_words` — words that triggered disfluencies in recent sessions
- `onset_weights` — phoneme-onset weights derived from per-word difficulty
- `covert_profile` — covert avoidance data (words the user has substituted away from)

Path: `wim_users/{uid}` in Firestore. Idempotency via MD5 of the serialized payload — no-op if hash matches the last publish.

WiM-side consumer NOT YET WIRED. Publisher publishes; nothing reads yet. That's Phase 2 of this feature.

### 3. Research memos (7 files under `docs/`)

Whitelisted in `.gitignore` via `!docs/<filename>.md` pattern (rest of docs/ stays ignored):

| File | Purpose | Target audience |
|------|---------|-----------------|
| `spanish_stuttering_memo.md` | Spanish-speaking PWS landscape | Bilingual foundation outreach |
| `multilingual_research_notes.md` | 10-language pack research | L4 prompt engineering |
| `stutterzero_checkpoint_research.md` | StutterZero paper analysis | Technical credibility with labs |
| `clinical_validation_protocol.md` | IRB-ready validation protocol | University speech labs |
| `l4_prompt_engineering_memo.md` | L4 system prompt rewrite rationale | Cross-project (feeds WiM `ReconstructClient.kt`) |
| `yolo_stutter_stutter_solver_evaluation.md` | YOLO-Stutter + DysfluentWFST eval | **Action: email Berkeley Speech Group for license** |
| `foundation_grant_landscape.md` | Foundations funding speech-disability R&D | Outreach email drafts |

Highest-leverage single action: email Berkeley Speech Group for DysfluentWFST license (per YOLO-Stutter memo).

### 4. Phase4 ears benchmark harness

`bench/_phase4_ears_benchmark.py` (1,058 lines) — runs the three WiM ears engines (Vosk, whisper.cpp, Qwen3-ASR) against labeled stutter audio and reports WER, insertion/deletion/substitution rates, disfluency-preservation rates, RTF on device, and side-by-side accuracy matrix.

**Never been run against all three branches yet.** That's the objective accuracy comparison needed before MERGE_PLAN execution on the WiM side.

### 5. Eval-build branch (institutional outreach)

`be07f7b` created `eval-build` branch — lighter-weight build for institutional demos. 8 fixes landed via `abb28f2` + `2690981`. Phase 2/3 evaluation scripts + matrices in `c096733`.

## Cross-project dependencies

- Lavrentiy publishes profile → **WiM consumes** (Firestore consumer not yet written on WiM side)
- Lavrentiy L4 prompt engineering memo → **WiM `ReconstructClient.kt` needs corresponding prompt update** (shell #3 is doing this; feat/l4-prompt-rewrite branch)
- Lavrentiy ears benchmark harness → **runs against WiM ears branches** for accuracy comparison

## Pending tasks (next-Claude punch list — Lavrentiy half)

1. **Run benchmark harness** against the three WiM ears branches. Command path TBD — inspect `bench/_phase4_ears_benchmark.py` for invocation args.
2. **Draft foundation outreach emails** using the three source memos: Spanish memo + foundation landscape + clinical protocol. Target: 5 foundations shortlisted in `foundation_grant_landscape.md`.
3. **Email Berkeley Speech Group** for DysfluentWFST license. Template + contact in YOLO-Stutter memo.
4. **Wire WiM-side Firestore consumer** — WiM reads `wim_users/{uid}` at login, applies trigger_words/onset_weights/covert_profile to its local L4 profile.
5. **Apply L4 prompt memo changes** once Claude shell #3 commits them to `feat/l4-prompt-rewrite`. Ports to both `lavrentiy.py` (desktop) and `ReconstructClient.kt` (Android).

## Agent orchestration — today's pattern

Five parallel streams ran most of the day (see WiM session log for the full table). On the Lavrentiy side specifically:
- **Sonnet 4.6 extended** produced the YOLO-Stutter memo + L4 prompt memo
- **gemini.com Deep Research** produced foundation landscape + Spanish memo
- **Claude main** committed + integrated

Rule reinforced: **one fat task per Gem CLI lifetime**. Violations cost hours on the WiM side.

## Wrong calls (Lavrentiy-specific)

1. **Python 3.14-alpha httpx bug wasted ~30 min** before falling back to stdlib urllib. Should have tested the huggingface download path first against a dummy model instead of integrating full Moonshine then debugging.
2. **Did not immediately add Moonshine test to `bench/`** — the RTF 0.35 number is a one-run anecdote, not a validated measurement. Benchmark harness has no Moonshine case.

## State summary

- **Desktop ASR:** Moonshine primary, Whisper API fallback, faster-whisper local fallback. Canary fully removed.
- **Firestore publisher:** written, tested, deployed. Consumer pending on WiM.
- **Research memos:** 7 committed, whitelisted, ready for outreach.
- **Benchmark harness:** 1,058 lines, ready but unexecuted against live ears branches.
- **`eval-build` branch:** institutional outreach build, 8 fixes.

## Quotes

- "we are not going to use the term stuttering... use the word speech disfluency" — George's terminology correction (WiM-relevant, logged here for cross-reference)
- "let's just make sure if for some reason this session goes bad... we have a map for the new session" — why this file exists

## Pointers

- **Sister session log (WiM side):** `C:\Users\georg\Documents\GitHub\wim-android\SESSION_LOG_2026-04-20.md`
- **Prior-session failure log:** `C:\Users\georg\Documents\GitHub\lavrentiy\SESSION_LOG_2026-04-19.md`
- **Memory dir:** `C:\Users\georg\.claude\projects\C--Windows-System32\memory\`
- **Full transcript (if compacted summary insufficient):** `C:\Users\georg\.claude\projects\C--Windows-System32\7bfebc81-5a84-4b8e-b7a4-08e28040766d.jsonl`
