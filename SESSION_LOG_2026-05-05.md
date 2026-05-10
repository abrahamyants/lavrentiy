# Session log — May 5, 2026 — Lav v1.6.0: drift-proof installer (rewrote the launcher)

Single-thread Lav session that started May 2 and got picked up across three days. End result: a fresh launcher path that doesn't share architecture with v1.5.7. Old installer kept untouched (different AppId, both can coexist).

---

## 1. Diagnosis: why v1.5.7 broke

George reported: "Engine launched once on my laptop, but stopped launching." Wife's laptop bringing up "a really old version from months ago."

Pulled `engine_err.log` from his active install at `C:\Users\georg\AppData\Local\Programs\Lavrentiy-Eval\engine\`:

```
File "...lavrentiy.py", line 44, in <module>
    import domain_pack
ModuleNotFoundError: No module named 'domain_pack'
```

Engine crashes immediately at import. Then `desktop.py` polls `/api/state` for 90 seconds, never gets a response (engine is dead), splash window hangs on "starting engine," eventually shows the red error page or just sits there. Exact match for the "stuck on first window" symptom.

**Root cause**: `installer/Lavrentiy-Eval.iss` manually enumerates each engine source file in the `[Files]` block. When `lavrentiy.py` grew imports (`domain_pack`, `l1_pack`, `rejection_store`, `style_examples`) over April 26-30, the .iss never grew alongside. Fresh installs got a `lavrentiy.py` that imports modules that aren't on disk → instant crash.

George's own machine "works" only because old install dirs accumulated those files from prior runs. Wife's laptop fresh v1.5.7 install: only has what v1.5.7 actually shipped.

## 2. Wrong path attempted first: PyInstaller --onefile

Initial reflex: PyInstaller `--onefile` to bundle everything into a single self-extracting .exe. Walked the import graph automatically → can't drift.

George caught it: "that PyInstaller shit sounds very familiar... I think there's a reason we didn't use it." Checked failure log #78 from `SESSION_LOG_2026-04-26-claude-session-2.md`: prior session tried `--onefile`, got 30-60s cold-launch every run because the bootloader re-extracts the ~660 MB bundle to `%TEMP%` on each launch. That session pivoted to `--onedir`. I was about to repeat the failure verbatim.

Killed the in-flight `--onefile` build at ~3 min (mid-Analysis). False-positive exit code 0 — same as failure log #81: when you `taskkill` PyInstaller's child python, the Bash background wrapper reports exit 0 from SIGTERM, NOT from successful build completion. Cleaned `build-onefile/` and `dist-onefile/` and restarted as `--onedir`.

## 3. Fix: PyInstaller --onedir + drift-proof Inno Setup

### Files added
- `lavrentiy_launcher.py` — 30-line entry point. Imports `lavrentiy`, opens browser to `localhost:7878` once port binds. No pywebview, no Qt, no splash screen. The dashboard lives in the user's default browser. Eliminates the entire `desktop.py` failure surface.
- `Lavrentiy-onedir.spec` — PyInstaller spec for `--onedir`. Bundles every sibling .py module + `l1_packs/` + `domain_packs/` + `lang_packs/` + `local/` + `silero_vad.onnx` + `dashboard.html` + `api_key.txt` + `anthropic_key.txt` + the bundled faster-whisper small.en model. Uses `collect_all()` for binary-heavy deps (`faster_whisper`, `ctranslate2`, `onnxruntime`, `sounddevice`, `soundfile`, `keyboard`, `openai`, `anthropic`, `metaphone`).
- `installer/Lavrentiy.iss` — new Inno Setup script. The entire `[Files]` section is one line:

  ```
  Source: "...\dist-onedir\Lavrentiy\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
  ```

  No manual file enumeration. PyInstaller already walked the import graph; we ship the result. Future imports added later → auto-bundled on next build → auto-shipped by Inno. No drift between releases.

### New AppId
`{B7E5F4A2-9C3D-4E1B-8A6F-2D8B5E9C1F3A}` — distinct from v1.5.7's. v1.5.7 layout was `{app}\engine\lavrentiy.py`; v1.6.0 layout is `{app}\Lavrentiy.exe + {app}\_internal\`. Incompatible enough that an in-place upgrade would scatter conflicting files. Fresh AppId means the two installs coexist and uninstall cleanly.

### Install target
`{userpf}\Lavrentiy` = `%LOCALAPPDATA%\Programs\Lavrentiy`. Per-user, no admin elevation, writable for runtime logs (`engine_err.log`, `engine_lifecycle.log`, `lavrentiy.pid`).

## 4. Build outputs

| Artifact | Path | Size | Status |
|---|---|---|---|
| PyInstaller dist folder | `dist-onedir/Lavrentiy/` | 1.6 GB | Built clean (~9 min) |
| Inno Setup installer | `installer/Output/Lavrentiy-Setup-v1.6.0.exe` | 749 MB | Built clean (~10 min, 607 sec ISCC) |

### Architecture-only test result

Killed George's running v1.5.7 engine (PIDs 16192 + 10368), ran the new `dist-onedir/Lavrentiy/Lavrentiy.exe`, observed:

- Port 7878 LISTENING within 8 seconds of launch (PID 5876)
- `GET /api/state` returns valid JSON (full engine state dict)
- No `ModuleNotFoundError` — every previously-missing module bundled correctly

What this verifies: imports resolve, HTTP server binds. **Not verified**: F9 hotkey records, Whisper transcription works, GPT-4o reconstruction call works, paste lands in active window, dashboard UI renders. End-to-end voice → text was deferred to George's manual smoke test. He can drive `localhost:7878` in browser + F9 anywhere when he picks this back up.

### Bloat note for v1.6.1

1.6 GB dist folder / 749 MB installer is bigger than v1.5.7's 575 MB. PyInstaller's `collect_all('faster_whisper')` and `collect_all('ctranslate2')` pulled CUDA + ROCm + DirectML compute backend variants. We only need CPU. Trimming those should drop the installer well below 500 MB. v1.6.1.

## 5. Code signing — researched, deferred

George read a market-scan summary on installer formats + signing options + distribution channels (Inno Setup vs NSIS vs WiX vs MSIX vs Velopack vs etc.). Confirmed Inno Setup + GitHub Releases is the standard solo-dev path. Code signing decision boiled down to:

- **SignPath Foundation** — free for OSS. **Blocked**: Lavrentiy has no `LICENSE` file. Project is "all rights reserved" by default. SignPath only signs OSI-licensed projects. Apache 2.0 is my recommendation if/when George picks (permissive + patent grant — relevant given the WiM IP filing pending decision).
- **Azure Trusted Signing** — $9.99/mo, no license requirement, US/Canada individuals supported. ~1-2 weeks identity verification.
- **Skip signing** (current path) — wife/recipient hits Edge "Keep" + SmartScreen "Run anyway" click-throughs once. Possible Defender quarantine on PyInstaller binaries (occasional, not edge case per George). Acceptable for eval distribution.

George's call: "We'll do it tomorrow" (license + signing path). Tonight the unsigned installer is ready.

## 6. Wrong calls / corrections

**Conflated license and signing.** When mapping the SignPath Foundation OSS-license requirement, framed it as part of the signing options instead of as a separate prerequisite. Made it look like I was making things up on the fly. George caught it: "first you said we need a license, then you say we can build an unlicensed version." The clean separation: license = legal status of source code; signing = trust signal on the binary; orthogonal except that one specific signing service has an OSS-license precondition.

**Over-hedged on AV quarantine probability.** Initial framing was "edge case, 5% chance." George pushed back: "this is not an edge case." He's right — PyInstaller binaries trip Defender heuristics regularly because the bundled-Python + compressed-archive + bootloader pattern looks like packed/obfuscated executables. Should have led with that honestly.

**Tried to replay the `--onefile` failure verbatim.** Caught only because George flagged "PyInstaller shit sounds very familiar." Saved by his memory of prior failure, not by my own check. Memory rule for next time: BEFORE proposing a build approach, grep the session logs for prior attempts at the same approach AND the failure log for matching failure modes. Don't trust that "this approach is clean architecture" without checking what already broke.

## 7. State at session pause

- `dist-onedir/Lavrentiy/Lavrentiy.exe` and `installer/Output/Lavrentiy-Setup-v1.6.0.exe` are both ready and untested past the HTTP smoke ping.
- Old v1.5.7 install on George's machine still on disk; engine processes were killed during my test, so anything depending on the v1.5.7 engine being alive is broken until George re-launches it OR installs v1.6.0.
- New engine PID 5876 was running through most of the session; status as of session end unknown (may have been killed when George closed his terminal).
- Wife's laptop test pending — needs the installer copied over via USB / Drive / share.
- Code-signing decision pending — license decision is the actual prerequisite.

## 8. Next-session pickup list

1. **End-to-end smoke test of v1.6.0** on George's laptop — `localhost:7878` in browser, F9 anywhere, verify the full voice → reconstruct → paste pipeline works.
2. **Wife's laptop install** — copy `Lavrentiy-Setup-v1.6.0.exe` over (USB or Drive), accept SmartScreen, install, verify.
3. **License decision + LICENSE file** — Apache 2.0 unless there's reason to choose otherwise. Required before SignPath Foundation can be applied to.
4. **SignPath Foundation application** — `signpath.org/apply`. Cert issued to "SignPath Foundation," requires attribution on a code-signing-policy page on the Lavrentiy site. 2-4 weeks onboarding.
5. **Trim ctranslate2 / onnxruntime CUDA + ROCm bloat** for v1.6.1 — drop installer size below 500 MB.
