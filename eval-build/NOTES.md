# Lavrentiy Evaluation Build — eval-build/

**This directory is NOT the cutting-edge source tree.** That lives at repo root (`lavrentiy.py`, `dashboard.html`, etc.). This directory is a frozen, minimally-patched branch of the engine used to produce the external-facing evaluation installer.

## What is this for?

George's currently running Lavrentiy process (at `C:\Users\georg\AppData\Local\Programs\Lavrentiy\`) feels noticeably faster and more stable than any prior iteration. We want to ship THAT version to institutions for evaluation — but with three targeted fixes applied so the first 5 minutes of a demo don't expose known crashes.

This directory is that "what George is running + three surgical fixes" version.

## What's inside

- `engine/lavrentiy.py` — patched engine (7,870 lines, from the 7,794-line Apr 13 installed snapshot + 76 lines added/changed across eight fixes)
- `engine/` other files — `dashboard.html`, `desktop.py`, `auth_google.html`, `mobile.html`, `onboard.html`, `manifest.json`, `sw.js`, `silero_vad.onnx`, `lavrentiy.ico`, `api_key.txt`, `gemini_api_key.txt`, `gemini_client.py`, `wim/`, `local/` — all identical copies from the current install (no changes)
- `engine/VERSION.txt` — eval version stamp

## Base version

- Source: `C:\Users\georg\AppData\Local\Programs\Lavrentiy\engine\` (the currently running install)
- Base engine `lavrentiy.py` last modified **2026-04-13 16:51**, 359,743 bytes, 7,794 lines
- Base installed dir last modified **2026-04-19** (desktop.py refresh)
- Current repo HEAD is **a222acb** (FAILURE LOG 23)

## What is NOT included from the repo (intentional)

The Apr 13 snapshot predates the April 19 repo work:

- `canary_transcribe()` function + Replicate wiring (was dormant anyway — `CANARY_ENABLED = False`)
- `pyautogui.FAILSAFE = False` (default remains ON in this build — only matters if the mouse hits a screen corner during paste)
- `POST /api/open-signin` endpoint (only relevant when dashboard runs in Edge `--app=` mode, which `desktop.py`'s pywebview wrapper doesn't need)

If a future evaluation surfaces a need for any of those, revisit case-by-case.

## The eight changes applied (vs the Apr 13 snapshot)

v1.2.0 = fixes 1–4 (crash/UX). v1.2.1 = adds fixes 5–8 (stutter accuracy + Falcon logic-leak + covert-avoidance acceptance).

### 1. Fix: Command Mode tuple-unpack bug

**File:** `engine/lavrentiy.py` line 6255

```diff
- whisper_result, _ = whisper_transcribe(tmp.name)
+ whisper_result = whisper_transcribe(tmp.name)
```

`whisper_transcribe()` returns a dict. The tuple-unpack raised `ValueError: too many values to unpack` on every Command Mode invocation, swallowed by the surrounding `except Exception`. Feature had never worked.

### 2. Guard: `reconstruct()` returns raw text when API key is missing

**File:** `engine/lavrentiy.py` line 2190

```diff
  """Layer 2+: Rebuild raw transcription into clean output."""
+ if client is None:
+     return raw_text
  # Detect if input contains Cyrillic (bilingual speaker)
```

Without this guard, the first F9 press on a fresh install with no API key raised `AttributeError: 'NoneType' object has no attribute 'chat'`, logged only as a generic "Error:" with no user-visible explanation.

### 3. Guard: `falcon_validate()` returns True when API key is missing

**File:** `engine/lavrentiy.py` line 2565

```diff
  which changes are expected per tone."""
+ if client is None:
+     return True
  tone_note = ""
```

Same root cause as fix #2, applied to the Falcon validator. Returning `True` skips the SAFE-mode rejection path — the raw text passes through unchanged.

### 4. Startup message when API key is missing

**File:** `engine/lavrentiy.py` line 973

```diff
  client = openai.OpenAI(api_key=API_KEY) if API_KEY else None
+ if client is None:
+     print("[Lavrentiy] No OpenAI API key found — L2+ reconstruction and Falcon validation disabled. L1 (disfluency filter) still works. Add key via dashboard or api_key.txt.")
```

Makes the missing-key state visible in the console log instead of silent.

### 5. Fix: L1 hyphenated stutter regex

**File:** `engine/lavrentiy.py` `strip_disfluencies()` (~line 2740)

```diff
- # Step 1: Remove stutter fragments (hyphenated false starts)
- # "p- p- pop" → "pop",  "be- be- become" → "become"
- cleaned = re.sub(r'(\b\w+)-\s+(?:\1-\s+)*', '', text, flags=re.IGNORECASE)
+ # Step 1: Remove stutter fragments (hyphenated false starts)
+ # Handles both spaced ("p- p- pop") and unspaced ("w-w-want", "s-schedule",
+ # "m-m-m-meeting") forms. Safety: first fragment must be a prefix of the
+ # full word (so "state-of-the-art" is safe); single-fragment cases with a
+ # common English prefix (re-, un-, pre-) are preserved.
+ def _strip_stutter(m):
+     frags = [f.strip() for f in m.group(1).strip().rstrip('-').split('-') if f.strip()]
+     full_word = m.group(2)
+     if not frags:
+         return m.group(0)
+     if len(frags) == 1 and frags[0].lower() in _ENGLISH_PREFIXES:
+         return m.group(0)
+     if full_word.lower().startswith(frags[0].lower()):
+         return full_word
+     return m.group(0)
+ cleaned = re.sub(
+     r'\b((?:\w{1,3}-\s*)+)(\w+)\b',
+     _strip_stutter, text, flags=re.IGNORECASE,
+ )
```

Old regex required `\s+` after every hyphen, so it missed every unspaced stutter: `w-w-want`, `s-schedule`, `m-m-m-meeting`, `n-next`, `d-d-discuss`, `ent-enterprise`, `s-s-software`. New regex accepts optional whitespace, uses two safety checks to preserve compound words (`state-of-the-art`, `twenty-one`, `e-mail`, `T-shirt`) and productive English prefixes (`re-read`, `un-done`, `pre-set`). Verified against 18-case harness in `_eval_strip_test.py`.

### 6. Fix: L1 word-repetition threshold lowered from 3+ to 2+

**File:** `engine/lavrentiy.py` `strip_disfluencies()` step 2 (~line 2765)

```diff
- # Require 3+ repetitions (2+ is often emphasis: "no no", "go go", "please please")
- cleaned = re.sub(r'\b(\w+)(?:\s+\1){2,}\b', _dedup_word, cleaned, flags=re.IGNORECASE)
+ # 2+ repetitions; NATURAL_REPEATS whitelist protects emphasis.
+ cleaned = re.sub(r'\b(\w+)(?:\s+\1){1,}\b', _dedup_word, cleaned, flags=re.IGNORECASE)
```

Old threshold caught "I I I" but let "to to", "the the", "for for" through — the most common stutter pattern after hyphenated fragments. New threshold catches all 2+ repeats; emphasis safety comes from the extended `NATURAL_REPEATS` whitelist (added: `really really`, `many many`, `much much`, `big big`, `long long`, `old old`, `hot hot`, `busy busy`, `right right`, `sure sure`, `fine fine`, `okay okay` on top of the existing set).

### 7. Fix: Falcon phonetic-context leak at L4

**File:** `engine/lavrentiy.py` `falcon_validate()` (~line 2561) + two call sites

```diff
- def falcon_validate(raw_text, clean_text, layer, tone="casual"):
+ def falcon_validate(raw_text, clean_text, layer, tone="casual", prof=None):
      """Binary meaning check. Returns True if meaning preserved.
-     Tone-aware: formal tone expands contractions, ..."""
+     ...
+     At layer >= 4, the speaker's hard onsets and known trigger words are
+     pulled from prof and injected so Falcon can flag phonetically-driven
+     avoidance substitutions (park→stop when /p/ is a hard onset) that a
+     semantics-only check misses."""
      ...
      elif layer >= 4:
+         phonetic_note = ""
+         if prof:
+             onset_weights = prof.get("onset_weights", {}) or {}
+             hard_onsets = [o for o, w in sorted(onset_weights.items(), key=lambda x: -x[1])[:5] if w and w > 0.5]
+             trigger_words = (prof.get("trigger_words") or [])[:10]
+             if hard_onsets:
+                 phonetic_note += f" Speaker struggles to produce words starting with: {', '.join(hard_onsets)}. ..."
+             if trigger_words:
+                 phonetic_note += f" Known trigger words for this speaker: {', '.join(trigger_words)}. ..."
          prompt = (
              "Speaker stutters. ..."
-             + tone_note + " Does the reconstruction preserve intended meaning? Answer ONLY 'yes' or 'no'."
+             + phonetic_note + tone_note + " Does the reconstruction preserve intended meaning? Answer ONLY 'yes' or 'no'."
          )
```

**Call sites updated** (lavrentiy.py lines 6058 + 7511):

```diff
- falcon_ok = falcon_validate(raw_text, clean_text, current_layer, current_tone)
+ falcon_ok = falcon_validate(raw_text, clean_text, current_layer, current_tone, prof=profile)

- falcon_ok = falcon_validate(raw_text, clean_text, layer, tone)
+ falcon_ok = falcon_validate(raw_text, clean_text, layer, tone, prof=profile)
```

**Why this matters:** Before the fix, `reconstruct()` at L4 received the full phonetic context (hard onsets, trigger words, Whisper confidence) and used it to inform reconstruction. But Falcon's L4 validation prompt was semantic-only — it checked "does meaning match" without any phonetic awareness. That meant the L4 LLM could hallucinate a phonetically-dissimilar but semantically-plausible synonym across a block (e.g., speaker blocks on `park`, Whisper hallucinates garble, LLM reconstructs as `stop the car`), and Falcon would wave it through as long as the sentence made sense. The speaker's actual intent silently replaced with a "close enough" alternative.

After the fix, Falcon at L4 receives the speaker's top 5 hard onsets and up to 10 known trigger words, and is explicitly told: *"If the reconstruction replaces a word starting with one of these with a different-onset synonym, answer 'no'."* Backward compatible — `prof=None` default means existing test harnesses work without modification.

### 8. Fix: Falcon L4 accepts reconstructions that reverse tracked covert avoidance

**File:** `engine/lavrentiy.py` `falcon_validate()` (~line 2608)

```diff
  # after hard_onsets + trigger_words injection above...
+ # Covert avoidance pairs — known patterns where the speaker replaces word X
+ # with word Y to dodge a hard onset. If the reconstruction REVERSES this
+ # (raw shows Y, reconstruction uses X), that is Lavrentiy CORRECTLY resolving
+ # a tracked avoidance. Falcon should accept it, not flag it as hallucination.
+ covert = (prof.get("covert_profile") or {}).get("avoidance_pairs") or {}
+ if covert:
+     pairs = []
+     for situ, words in covert.items():
+         for avoided, data in words.items():
+             subs = (data or {}).get("common_substitutes") or []
+             if subs:
+                 pairs.append(f"{avoided} (commonly dodged via: {', '.join(subs[:3])})")
+     if pairs:
+         phonetic_note += (
+             f" Known covert avoidance patterns: {'; '.join(pairs[:5])}. "
+             "If the reconstruction REVERSES a known avoidance (raw transcription "
+             "contains the substitute, reconstruction uses the original intended "
+             "word), that is CORRECT — answer 'yes'. Only flag substitutions that "
+             "introduce NEW avoidance away from the speaker's hard onsets."
+         )
  # Final L4 prompt question line tweaked:
- "Does the reconstruction preserve intended meaning? Answer ONLY 'yes' or 'no'."
+ "Does the reconstruction preserve intended meaning without unwarranted "
+ "phonetic hallucination? Answer ONLY 'yes' or 'no'."
```

**Why this was needed (what fix #7 missed):** Fix #7 closed the leak in the "catch NEW avoidance" direction — if L4 reconstructs `park → stop the car` against a speaker whose /p/ is a hard onset, Falcon now rejects. But fix #7 would ALSO reject the opposite direction: if the user has a known history of avoiding `door → entrance` and Lavrentiy CORRECTLY reconstructs `entrance → door` (resolving the tracked covert avoidance — exactly what Layer 4 is supposed to do), fix-#7-Falcon would see a different-onset substitution and flag it. That would be Falcon fighting the system it's supposed to validate.

Fix #8 reads `profile["covert_profile"]["avoidance_pairs"]` — the same structure described in the README's "Covert Stuttering Detection" section (tracks per-situation word-level avoidance with `avoided_count`, `used_count`, `common_substitutes`). It injects a whitelist of known avoidance reversals into Falcon's L4 prompt, explicitly telling it: *"REVERSALS are CORRECT, only flag NEW avoidance."*

Final question line also updated to use "unwarranted phonetic hallucination" — cleaner framing borrowed from an external review.

**Origin credit:** fix #8 was surfaced by an external model's read of the same code — it spotted the covert_profile angle that fix #7 missed. Tested in combination they cover both directions of phonetic drift: rejecting NEW avoidance (fix #7) AND accepting reconstructions that reverse tracked avoidance (fix #8).

## How the installer uses this

`installer/Lavrentiy-Eval.iss` pulls files from TWO places:

1. **Launchers + bundled Python** from `C:\Users\georg\AppData\Local\Programs\Lavrentiy\*` (excludes `engine\*`)
2. **Patched engine** from `C:\Users\georg\Documents\GitHub\lavrentiy\eval-build\engine\*`

Installs as **Lavrentiy Evaluation** to `Program Files\Lavrentiy-Eval\`, with its own Start Menu group and (optional) desktop shortcut. Lives alongside the Current install without conflict.

## Rebuild command

```
"C:\Users\georg\AppData\Local\Inno Setup 6\ISCC.exe" \
  "C:\Users\georg\Documents\GitHub\lavrentiy\installer\Lavrentiy-Eval.iss"
```

Output: `installer\Output\Lavrentiy-Eval-Setup-v1.2.1.exe`
