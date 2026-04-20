# Lavrentiy Evaluation Build — eval-build/

**This directory is NOT the cutting-edge source tree.** That lives at repo root (`lavrentiy.py`, `dashboard.html`, etc.). This directory is a frozen, minimally-patched branch of the engine used to produce the external-facing evaluation installer.

## What is this for?

George's currently running Lavrentiy process (at `C:\Users\georg\AppData\Local\Programs\Lavrentiy\`) feels noticeably faster and more stable than any prior iteration. We want to ship THAT version to institutions for evaluation — but with three targeted fixes applied so the first 5 minutes of a demo don't expose known crashes.

This directory is that "what George is running + three surgical fixes" version.

## What's inside

- `engine/lavrentiy.py` — patched engine (7,800 lines, from the 7,794-line Apr 13 installed snapshot + 6 lines added across four fixes)
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

## The four changes applied (vs the Apr 13 snapshot)

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

Output: `installer\Output\Lavrentiy-Eval-Setup-v1.2.0.exe`
