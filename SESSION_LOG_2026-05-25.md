# Session log — May 25, 2026 — Code review pass + native window pivot

Long session that started as "let me launch the desktop app" and turned into (1) a multi-hour QtWebEngine flicker hunt that ended with a pivot to pywebview+WebView2, (2) two real toggle bugs in the dashboard wiring, (3) a comprehensive complexity-bomb refactor pass across the seven worst Python functions, plus (4) infrastructure side-quests: laptop performance cleanup, phone bridge updates, OpenSSH server on Windows, persistent SSH via Termux:Boot.

---

## 1. The flicker hunt (where the session burned the most time)

Goal: launch the native PySide6+QWebEngineView variant George had referenced. Built the spec with `python -m PyInstaller Lavrentiy.spec`, dropped a desktop shortcut, double-click.

Result: window opens, **flickers like a strobe light**.

What WORKED before pivoting:
- Confirmed it was bundle-specific, not source — `python native/lavrentiy_app.py` ran clean from source.
- Sandbox bypass attempts: `QTWEBENGINE_DISABLE_SANDBOX=1`, explicit `QTWEBENGINEPROCESS_PATH`. No effect.
- DPI lockdown: `QT_AUTO_SCREEN_SCALE_FACTOR=0`, `QT_SCALE_FACTOR=1`, `--force-device-scale-factor=1`. No effect.
- ANGLE D3D11 backend: `QTWEBENGINE_CHROMIUM_FLAGS="--use-angle=d3d11 --in-process-gpu"`. Reduced flicker frequency, didn't stop it.
- Custom crash logger with `sys.excepthook` + `faulthandler.enable` + stdout/stderr redirect to log file. Confirmed it WASN'T a Python exception (log was empty), WASN'T a Windows event-log fault, WASN'T a QtWebEngineProcess respawn loop (steady 1 helper).
- CDP remote debugging probe via `QTWEBENGINE_REMOTE_DEBUGGING=9223` + WebSocket script reading `Performance.getMetrics`. Showed `LayoutCount: +0, RecalcStyleCount: +24/3s, Frames: +0` — meaning **Chromium thought the page was rendered and stable**. So the flicker wasn't paint-cycle.
- Diagnostic test: swapped `dashboard.html` for a minimal "Hello World" page in the bundled `_internal/` dir. Result: minimal page **rock stable**, no flicker. Therefore the flicker was in dashboard.html, not QtWebEngine.

What ACTUALLY caused the flicker — found by reading `dashboard.html` and the `start_engine()` code path together:
- Dashboard.html line 3199 hardcodes `const API='http://127.0.0.1:7878';`.
- Line 3818: `setTimeout(pollState, 250)` — polls `/api/state` every 250ms.
- The native variant called `start_engine(run_http_server=False, block=False)`. That flag gated BOTH the HTTP server AND the system tray icon behind one condition. So **the dashboard's polling was hitting a closed port four times per second**, each failure triggering a state update + DOM rebuild → visual flicker.

The fix wasn't in the bundle, the sandbox, or QtWebEngine. It was a one-character architectural error: `run_http_server` was overloaded ("am I the HTTP variant?" + "should I run an HTTP server?"). Decoupled in `lavrentiy.py:8324` — HTTP server now always starts (dashboard.html requires it), only the tray + auto-open-browser remain gated by the original flag.

### Failure: time lost on this

~90 minutes chasing wrong theories (QtWebEngine sandbox, GPU compositor, DPI, ANGLE backend) before instrumenting properly. The CDP probe was the diagnostic that flipped the search — Chromium reporting `Frames: +0` was the smoking gun pointing AWAY from a render-loop and TOWARD an external cause. Should have done CDP probing earlier; instead defaulted to env-var workarounds because "other LLM said sandbox crashes."

### The pivot

Even after fixing the polling bug, the native QWebEngineView variant still flickered SUBTLY when rendering the real dashboard.html — and the diagnostic test confirmed the dashboard.html exercises CSS that QtWebEngine's Chromium (~Qt 6.11 fork, 12–18 months behind real Chrome) handles poorly while real Chrome handles fine.

Bailed on QtWebEngine entirely. Replaced with `pywebview` + WebView2 (Microsoft Edge's current Chromium runtime, already shipped on Windows 10/11 since 2021). New entry point: `native/pywebview_app.py` (~70 lines, replaces a 160-line PySide6 spaghetti file). Bundle size drops from ~1 GB to ~50 MB. No flicker class of bugs at all because WebView2 = real-current Chromium = same engine as the HTTP+Chrome variant.

Desktop shortcut now points directly at `pythonw.exe` with `pywebview_app.py` as arg. Engine runs as a non-daemon thread so closing the pywebview window doesn't kill the engine — user controls quit via the system tray icon (right-click → Quit Lavrentiy).

---

## 2. Two actual toggle bugs the dashboard ate silently

While testing the post-pivot Lavrentiy, George flagged "I can't toggle L1 ASR cloud/local." Tracked it:

1. `/api/l1_asr` POST endpoint had a handler (`handle_POST_api_l1_asr` at line 7748) but **was never wired into `dispatch_api`**. Calls returned 404, dashboard's `toggleL1Asr()` failed silently inside its `catch(e){}` block. Added the route entry. Now the toggle works.

2. Paralinguistic + Prosodic toggles "didn't respond." Reading `dashboard.html:3920`, the UI hardcoded `_isL4 = (state.layer||0) >= 4` and DISABLED both inputs unless on L4. But the engine consumes para/pros on every reconstruct() call (L2+). Mismatch.

   Replaced the hardcoded L4 check with server-provided `state.paralinguistic_available` / `state.prosodic_available` booleans. Engine now decides per-layer:
   - L1 (transcribe-only, no reconstruct call) → force OFF + grey out
   - L2/L3/L4 → user-controlled

   Removed the line in `set_layer()` that force-enabled prosodic on every L4 switch (which made "toggling off" feel impossible — switch layer once and it comes right back on).

---

## 3. Comprehensive complexity-bomb refactor (lavrentiy.py + wim/api/)

Ran the static-analysis stack (ruff, vulture, radon, lizard, pyright, eslint, stylelint, htmlhint, mutmut, py-spy). Identified 7 functions ranked F or E by radon. Decomposed 6 fully, 1 partially:

| Function | Before | After | New helpers |
|---|---|---|---|
| `generate_clinical_profile` | F (47) | **A (2)** | 14 single-purpose section helpers (`_cp_period`, `_cp_primary_disfluency`, `_cp_situational_breakdown`, etc.) |
| `dispatch_api` | F (62) | **B (6)** | Replaced if-elif chain (56 routes) with two module-level dict-dispatch tables |
| `handle` (wim/api/main.py) | E (31) | **B (6)** | Five `_action_*` helpers (`_action_sync_profile`, `_action_export_data`, `_action_delete_data`, `_action_command`, `_action_reconstruct`) + `_classify_exception` |
| `infer_speaker_state` | E (43) | **B (6)** | `_compute_session_prosodic_aggregates`, `_compute_baseline_deviations`, `_classify_speaker_state` |
| `detect_paralinguistic_events` | F (51) | **B (9)** | `_localize_candidate_window`, `_classify_unknown_event_type`, `_passes_duration_gate`, `_build_voiced_event`, `_build_pause_breathing_event` |
| `build_prompt` (wim/api/prompt_builder.py) | F (65) | **C (13)** | 8 prompt-section helpers (`_pb_severity_aggression`, `_pb_layer3_user_context`, `_pb_whisper_signals`, `_pb_layer2_3_restate`, `_pb_layer4_block`, `_pb_layer4_clinical_core`, `_pb_paralinguistic_events`, etc.) |
| `pipeline` | F (136) | F (101) | Partial — 6 helpers (`_run_l1_haiku_polish` + `_render_polish_diff_html`, `_detect_and_fallback_on_llm_leak`, `_clean_and_filter_text`, `_run_l4_stutter_analytics`, `_run_l2plus_learning_loops` + `_spawn_bg_l1_autodetect`, `_detect_redo_and_update_style_pair`). Remaining complexity is global-state mutation (profile dict, `_learn_counter`, `_decay_counter`, `_last_*` caches, `_profile_switch_epoch`) — further extraction needs a `PipelineContext` dataclass rather than more helpers with 8-arg signatures. Stopped here on purpose. |

Verified end-to-end after each major refactor by restarting the engine and curling endpoints:
- All 56 API routes still respond correctly after `dispatch_api` refactor
- `/api/clinical_profile` produces the same shape after the 14-helper split
- `/api/reconstruct_test` returns clean output on canonical input after `build_prompt` decomposition
- L1/L2/L3/L4 layer switching produces correct `paralinguistic_available`/`prosodic_available` flags

Plus low-level cleanup:
- 3 dead `return` statements removed after working `return {'error': ...}` lines (cosmetic — caught by vulture)
- `ruff --fix` auto-cleaned 33 lint issues across `lavrentiy.py`, `native/*.py`, `wim/api/*.py` (unused imports, f-strings without placeholders, multi-statement-on-one-line semicolons)
- 35 silent `catch(e){}` blocks in dashboard.html replaced with `catch(e){console.warn('silent catch:', e)}` so future bugs leave a trail (this exact pattern is what made the flicker bug invisible)
- **Real bug found by eslint no-undef**: `dashboard.html:5563` Escape-key handler called `closeProfile()` — function doesn't exist; actual function is `closeProfileModal()`. Silently failed. Fixed.

---

## 4. Failures during the refactor pass

- **Over-claimed pyright "critical" findings**: My initial report flagged 29 `reportOptionalMemberAccess` errors as "29 None-dereference risks waiting to crash." Closer reading showed most are wrapped in surrounding `try/except` and are pyright over-strictness, not real bugs. Walked it back.
- **Over-claimed the Anthropic SDK `block.text` issue**: Reported as critical bug; the code actually checks `getattr(b, "type", None) == "text"` before accessing `.text` — type-safe at runtime, just opaque to pyright's narrowing. False positive in my report.
- **Test suite measures zero coverage**: 21 `test_*.py` files exist at repo root, all "pass" — but they're script-style (do `sys.exit(0)` at module load) and don't `import lavrentiy` as a module. pytest can't collect them; coverage.py reports zero against the engine; mutmut is blocked by the same. This is structural debt — needs the test suite restructured into pytest-style before any quantitative test-quality measurement is possible.

---

## 5. Side quests (infrastructure work)

Not strictly Lavrentiy code but happened in this session:

- **Laptop performance cleanup**: Defender exclusions for dev folders, killed Waves audio service (Realtek replacement), uninstalled Dell SupportAssist family (preserving Dell Optimizer / Core Services / AppCore — those broke the desktop last time per the memory note). CPU baseline dropped from 74% to ~13%. Disabled hibernation (freed 12.7 GB). Deleted Win11_25H2.iso (7.89 GB — already installed). Killed orphan BarTender SQL Server instance (535 MB RAM back).
- **Phone bridge**: SSH from laptop → Flip7 was broken because the previous Fold's pubkey wasn't on the new device. Re-pushed via `adb shell run-as com.termux ...`. Installed Termux:Boot from GitHub releases (NOT F-Droid — signature mismatch with the Termux app George already had). Added boot-time `~/.termux/boot/start-sshd` that acquires `termux-wake-lock` + runs `sshd`. SSH now survives screen-off, Doze, reboots.
- **OpenSSH Server on laptop**: Installed via `Add-WindowsCapability OpenSSH.Server`. Phone's pubkey added to `C:\ProgramData\ssh\administrators_authorized_keys` (the file Windows OpenSSH actually reads for admin users — NOT the user's `.ssh/authorized_keys` which is silently ignored). Bound to Tailscale IP only. Phone can now SSH back into laptop via `ssh laptop` (config alias).

---

## 6. What was deliberately NOT done

- **`pipeline` final decomposition**: Stayed at F (101) instead of pushing for A/B. Remaining complexity is shared global state across the function body; cleaning it up requires a `PipelineContext` dataclass refactor — a few hours of work with non-trivial regression risk on the recording flow. Returns are marginal at this point.
- **`applyI18n` in dashboard.html**: ~250 lines of distinct DOM-pattern handlers, CC=50. Could be split into ~15 small helpers but: (a) pure cosmetic refactor with no observable benefit, (b) hard to verify (need to switch languages and click through every screen), (c) the patterns are heterogeneous enough that a table-driven approach won't compress them. Skipped.
- **Switching test suite to pytest-style**: Big structural change to 21 files. Worth doing, but not in this session.
- **Native PyInstaller variant**: The PySide6 bundle is now dead architecture. Kept the spec + build scripts in place but the desktop shortcut points at the pywebview launcher instead. If someone wants to revive PySide6, the path is `python -m PyInstaller Lavrentiy.spec --distpath dist-native` then deal with the dashboard CSS that QtWebEngine renders poorly.

---

## Files modified this session

- `lavrentiy.py` — refactors + `/api/l1_asr` route + paralinguistic/prosodic policy + always-start HTTP server fix
- `dashboard.html` — Escape-key handler fix, server-provided availability flags, silent-catch → console.warn
- `wim/api/main.py` — `handle` decomposition into 5 action helpers
- `wim/api/prompt_builder.py` — `build_prompt` decomposition into 8 prompt-section helpers
- `wim/api/contribute/main.py`, `wim/api/l1_pack.py`, `wim/api/reconstruct.py` — minor ruff --fix cleanup (unused imports / vars)
- `native/lavrentiy_app.py` — extensive crash-logging instrumentation + sandbox env vars (dead path now, retained for reference)
- `native/pywebview_app.py` — NEW. The actual native window entry point. WebView2 via pywebview, ~70 lines.

## Files added to .gitignore

- `.coverage` (coverage.py runtime artifact)
- `style_examples.json` (engine-written runtime data — `style_examples` module's persistent store)
