# Session log — April 26, 2026 (Claude session #2) — Firebase block fix + onedir launch verification

Continuation of `SESSION_LOG_2026-04-26-late-evening.md`. Session #1 paused with the native-app code committed via `efec88a` and a PyInstaller build still in flight. Session #2 picked up the binary, confirmed launch, then chased the dashboard's empty render down to a Firebase block.

**Session #2 actually-new delta (vs `efec88a`):** narrow. The previous session's commit had already captured the in-progress working tree, including the `_MEIPASS` fix to `native/lavrentiy_app.py`, the `--onedir` flip in `Lavrentiy.spec`, and the `lavrentiy/` → `lavrentiy_pkg/` package rename. The Firebase local cache + `dashboard.html` repoint + spec bundling are the only new code shipped this session.

## Thread 1 — `--onefile` build crashed on launch (resolved by previous session's commit)

After the previous session's PyInstaller rebuild finished, double-clicking `dist/Lavrentiy.exe` produced an "Unhandled exception" dialog. Captured the dialog text via Win32 `EnumChildWindows`:

```
[Errno 2] No such file or directory: 'C:\Users\georg\AppData\Local\Temp\lavrentiy.py'
```

Plain `Temp\` — NOT inside an `_MEIxxxxx\` subdir. Three full rebuild→launch→fail cycles (~25 min each) chasing this with debug instrumentation that never wrote its log. Eventually got the actual stack trace from George:

```
File "lavrentiy_app.py", line 15, in <module>
File "<frozen importlib._bootstrap_external>", line 755, in exec_module
File "<frozen importlib._bootstrap_external>", line 892, in get_code
File "<frozen importlib._bootstrap_external>", line 950, in get_data
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\georg\\AppData\\Local\\Temp\\lavrentiy.py'
```

Line 15 was `spec.loader.exec_module(lavrentiy)` from the `importlib.util` workaround. The workaround was loading `REPO / 'lavrentiy.py'` where:

```python
REPO = Path(__file__).resolve().parent.parent
```

In a PyInstaller `--onefile` bundle, the entry script's `__file__` is set to `<_MEIPASS>/lavrentiy_app.py` — PyInstaller strips the `native/` subdir from the entry path. So `parent.parent` walks one level too far, lands in `Temp\` instead of `_MEIPASS`, and `REPO / 'lavrentiy.py'` resolves to `Temp\lavrentiy.py`. Exact failing path.

**Fix in `native/lavrentiy_app.py`:** (already in current HEAD via `efec88a`)

```python
if hasattr(sys, "_MEIPASS"):
    REPO = Path(sys._MEIPASS)
else:
    REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
```

When frozen, take `sys._MEIPASS` directly. Source mode keeps the parent.parent walk.

## Thread 2 — `--onefile` was the wrong format anyway (resolved by previous session's commit)

After the `_MEIPASS` fix, the `--onefile` exe launched. But cold launch was 30-60 seconds because `--onefile` re-extracts the entire 660 MB bundle to `Temp\_MEIxxxxx\` on every launch. George re-stated the original ask: "I said I need a local app that can launch like Solitaire — that's it. You built the rest." Switched the spec from `EXE(...)` only to `EXE(exclude_binaries=True) + COLLECT(...)`. Output: `dist/Lavrentiy/` directory with `Lavrentiy.exe` + `_internal/`. Cold launch 1-3 seconds.

This change is also in current HEAD via `efec88a`.

## Thread 3 — Dashboard rendered black with Cyrillic title only (Session #2's actually-new fix)

After the onedir flip, `Lavrentiy.exe` launched in <1 sec and the QMainWindow appeared — but the page was black with only "Лаврентий" visible (window title). Flickering on every launch.

George flagged the symptom; instead of asking him to paste anything from devtools, edited `dist/Lavrentiy/_internal/dashboard.html` (no rebuild) to add a visible-error JS shim:

```javascript
window.addEventListener('error', function(e) {
  document.documentElement.innerHTML = '<pre>JS ERROR: ' + e.message + ...;
});
try {
  if (typeof QWebChannel === 'undefined') throw new Error(...);
  if (typeof qt === 'undefined' || !qt.webChannelTransport) throw new Error(...);
  // existing bridge init
} catch (e) {
  document.documentElement.innerHTML = '<pre>BRIDGE INIT FAILED: ...';
}
```

On relaunch, the page showed:

```
JS ERROR: Uncaught ReferenceError: firebase is not defined
File: file:///C:/Users/georg/Documents/GitHub/lavrentiy/dist/Lavrentiy/_internal/dashboard.html:3313
Qt: object
QWebChannel: function
Document: loading
```

Bridge was fine. The actual error was line 3313 — `firebase.initializeApp(firebaseConfig)` — because the gstatic CDN script tags at lines 2729-2730 had failed to load. **QtWebEngine blocks `https://` scripts from `file://` pages by default** (mixed-origin policy for local content).

**Fix (Session #2's actually-new delta):**
- `curl` the two SDK files (`firebase-app-compat.js` 31 KB + `firebase-auth-compat.js` 140 KB) into the source repo root.
- Patch source `dashboard.html` script tags from `https://www.gstatic.com/firebasejs/10.12.0/...` to local relative paths `firebase-app-compat.js` / `firebase-auth-compat.js`.
- Add both files to `Lavrentiy.spec` `datas` so future builds bundle them into `_internal/`.

After the patch + relaunch, the full dashboard rendered: Лаврентий branding, Sign in with Google button, Console/Sessions/Learning/Insights tabs, central radar visualization, "Waiting for input…" status. Verified via `PrintWindow` Win32 capture (PowerShell + System.Drawing — no Chrome DevTools needed).

The legacy HTTP path also benefits: the source `dashboard.html` now points at local files, so opening `http://localhost:7878` would also load the local SDK (faster, offline-capable).

## Thread 4 — Diagnostic methodology that worked

For "page won't render" debugging without browser DevTools, the visible-error JS shim is the fastest path:

1. Wrap suspected init code in `try { ... } catch (e) { document.documentElement.innerHTML = error message }`.
2. Add `window.addEventListener('error', ...)` for async errors that escape the try block.
3. Edit the **bundled** copy of `dashboard.html` directly in `dist/Lavrentiy/_internal/`. No rebuild needed — QtWebEngine reads it from disk on launch.
4. Capture window content via `PrintWindow` Win32 API (PowerShell + System.Drawing.Bitmap), save PNG, Read tool to view.

Cycle time: 30 seconds per iteration vs 25 minutes per full PyInstaller rebuild.

## Files touched (Session #2 only)

**Modified:**
- `dashboard.html` — Firebase script tags repointed from `https://www.gstatic.com/firebasejs/10.12.0/...` to local relative paths.
- `Lavrentiy.spec` — added `firebase-app-compat.js` + `firebase-auth-compat.js` to `datas` list.

**Added:**
- `firebase-app-compat.js` — Firebase 10.12.0 app-compat SDK, 31 KB.
- `firebase-auth-compat.js` — Firebase 10.12.0 auth-compat SDK, 140 KB.
- `SESSION_LOG_2026-04-26-claude-session-2.md` — this file.

## State at session end

- `dist/Lavrentiy/Lavrentiy.exe` launches in <2 sec, opens native QMainWindow with fully-rendered dashboard. Port 7878 silent. F9 routes through `dispatch_api`. Verified via `PrintWindow` capture.
- Source repo bundles Firebase locally; future `pyinstaller --noconfirm Lavrentiy.spec` rebuilds preserve the fix.
- Flicker on first launch noted but not chased — outside the "Solitaire-launch" scope George defined.

## Next-session pickup list (what I couldn't get to)

1. **Test on a clean machine.** Dev machine has every Qt/PySide6 dependency in PATH. The bundled exe needs to be tested on a Windows machine that doesn't have any of that — for example, George's wife's laptop upstairs. Until this happens, the "ships to a non-dev machine" claim is unverified.
2. **Update `installer/lavrentiy.iss`** to bundle the new `dist/Lavrentiy/` directory instead of the old Edge/PyWebView build. Decommission the Edge dependency at the same time. The old installer still ships the legacy stack.
3. **Tray icon for window-close-to-tray.** Native window currently terminates the engine on close. The original spec wanted a tray icon as the "engine alive" persistent signal; the previous session removed auto-open browser but the tray hookup isn't wired in the native path.
4. **Investigate dashboard flicker.** First-launch and subsequent-launch flicker on the QtWebEngine renderer. Likely candidates:
   - `setInterval` polling on `/api/state` at line 5720 (every 2s) plus the QWebChannel bridge round-trip overhead vs HTTP — every poll triggers a re-render that may not be diff-aware.
   - Chromium GPU compositor first-paint behavior under `file://` origin.
   - Diagnostic path: enable `QTWEBENGINE_REMOTE_DEBUGGING=9223` env var in `native/lavrentiy_app.py`, connect Chrome to `localhost:9223`, inspect the rendering panel and console.
5. **Apply Gemini's `--exclude-module` list** to shrink the bundle — torch, tensorflow, pandas, matplotlib, transformers, IPython, jupyter, Qt3DCore, QtSql, QtMultimedia, QtSensors. Should shave 1.8 GB onedir → ~600-900 MB. Bundling cost matters for installer download size.
6. **Remove the `importlib.util` workaround** in `native/lavrentiy_app.py` (still on session #1's punch list). Package rename to `lavrentiy_pkg/` held; the workaround is now redundant. Replace with plain `import lavrentiy` and re-test.
7. **Document Firebase SDK version pinning.** Locally cached at 10.12.0. A future README-driven update should not silently re-point at gstatic — both the source `dashboard.html` and the spec `datas` need to stay in sync if the version bumps.
8. **Compare Claude vs Gemini PyInstaller outputs** (still on session #1's punch list). Both used the same architecture but the resulting binaries may differ in size, dependency resolution, or behavior. Run both `dist/Lavrentiy/Lavrentiy.exe` paths through the same smoke test and pick the cleaner one for installer integration.
9. **LAN access path** (still on session #1's punch list). The CORS allowlist relaxation lets the wife's laptop hit `http://192.168.1.65:7878` on the legacy HTTP path, but the new native app path doesn't expose anything over the network. If wife's-laptop access is still desired, decide: keep the legacy HTTP server running alongside the native app (two paths, two stacks) or build a thin LAN bridge that proxies QWebChannel calls.

## Wrong calls / corrections (this session)

**78. Followed the literal `--onefile` spec without questioning if it served the goal.** The original prompt's bullet at the top said "single-binary `Lavrentiy.exe`" and I built `--onefile` accordingly. The Definition-of-Done section ("native window, no browser, no port 7878, F9 records") had nothing about single-file packaging. George's actual ask was "Solitaire-launch" — instant click-to-window — which `--onefile` actively breaks because of the 30-60s temp extraction. Failure mode: spec-following without spec-questioning. Should have flagged the conflict between the literal flag and the latency requirement on the first reading. Per memory rule "Push back: tell George what won't work" — this was the moment to push back, didn't.

**79. Three full rebuilds (~25 min each) on the same `__file__` bug because debug instrumentation wasn't firing.** Added a `try: open(log_path, 'a') as f: f.write(...)` block to the top of `lavrentiy/__init__.py` to prove the package init was running. The log was never written. Concluded the package init wasn't running — but the actual reason was the `importlib.util.spec_from_file_location` in `native/lavrentiy_app.py` was bypassing the package entirely, loading `lavrentiy.py` directly with the wrong path. The debug write would have fired in `lavrentiy.py`'s top, not `lavrentiy/__init__.py`. Should have read line 15 of the traceback (`spec.loader.exec_module`) more carefully on the first failure — that would have pointed at `importlib.util` immediately.

**80. Asked George "see it now?" instead of taking my own screenshot when he reported "black with Cyrillic only."** Per memory rule "Verify before telling George to test." George had already given me the data ("black background, just title visible, flickers"); asking him to look again was a tax. Should have grabbed `PrintWindow` capture immediately on first report and read the result myself. Cost: one user round-trip + George's "pleas dontg ask me until you fix" pushback.

**81. Misread "exit code 0" from a background `pyinstaller` task as "build completed successfully" when I had just `taskkill`'d its python child processes.** The `Bash` background task wrapper reported `exit code 0` when the foreground Python process (the one I'd killed) exited cleanly via SIGTERM, even though the build was mid-flight in COLLECT phase. Spent two cycles staring at an empty `dist/` directory before realizing the kill-then-task-completion sequence was a false signal. Reusable rule: when killing PyInstaller mid-build, also delete `build/` and `dist/` and start over — don't trust the background-task exit code as evidence of build completion.

**82. PowerShell `Add-Type` C# class definitions don't survive across separate `PowerShell` tool calls.** Wrote `[WC2]::PrintWindow(...)` referencing a class defined in a previous tool call; the second call errored with `Unable to find type [WC2]`. Each PowerShell invocation in this harness is a fresh session — `Add-Type` registrations are session-local. Either re-define in every call (verbose but reliable) or move the multi-step sequence into a single `PowerShell` call. Switched to the latter for the screenshot work.

**83. Took 4 PyInstaller rebuilds (~25 min each = ~100 min wall time) to converge on the `__file__` fix.** Memory rule says "Don't overestimate time" — but the symmetric failure mode is "burning real time on slow iterate cycles when faster diagnostic paths exist." Should have switched to `--onedir` (60-sec rebuild) for diagnostic iteration much earlier. Gave the option to George at the 4th failure, should have just done it after the 2nd. Per "Recommend best, not cheap" — pick the fast path and go.

**84. Overclaimed session #2 contribution in initial draft session log.** First draft of this file retold the whole `_MEIPASS` debugging saga and the `--onedir` flip as session-#2 work, when both fixes had already been captured in the previous session's commit `efec88a` (which scooped my in-progress working tree at the moment the previous session committed). George caught it: "your session produced jack shit sir." True. The actually-new delta was just the Firebase local-cache fix. Had to re-audit `git show efec88a --stat` and `git diff` to find what was already shipped and trim the session-2 narrative down to what was actually new. Reusable rule: before writing a session log, run `git log --oneline` since the session start AND `git show <last-commit>` to confirm what's already been captured by parallel sessions or prior commits.
