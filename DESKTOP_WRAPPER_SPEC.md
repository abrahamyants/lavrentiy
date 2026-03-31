# Lavrentiy Desktop Wrapper — Spec for Sonnet

## What This Is

Lavrentiy is a voice reconstruction engine (`lavrentiy.py`, 6,490 lines). It currently runs as a background Python process (`pythonw.exe`) and serves a browser dashboard (`dashboard.html`) on `localhost:7878`. The user has to open Chrome and navigate to `http://localhost:7878` to use the dashboard.

**Goal:** Wrap the existing engine + dashboard into a proper Windows desktop app using **pywebview**. No Electron. No new UI framework. The existing `dashboard.html` stays exactly as-is — pywebview just puts it in a native window instead of a browser tab.

## Repo Location
`C:\Users\georg\Documents\GitHub\lavrentiy\`

## Current Architecture
- `lavrentiy.py` — single-file engine. Runs as background process. Starts an HTTP server on port 7878. Serves `dashboard.html` and REST API endpoints (`/api/state`, `/api/toggle/*`, etc.)
- `dashboard.html` — browser-based control panel. Polls `/api/state` every 750ms. All frontend is self-contained in this single HTML file (no build step, no node_modules).
- `lavrentiy.bat` — current launch script, runs `pythonw lavrentiy.py`
- Engine uses hotkeys (F9=talk, F10=tone, F11=layer, F12=stats, F3x3=quit) via the `keyboard` library
- Single-instance enforcement via Windows mutex (`Global\LAVRENTIY_SINGLE_INSTANCE`)

## What to Build

### 1. `desktop.py` — New file (~150-200 lines)

This is the desktop wrapper. It does three things:
1. Starts the engine (`lavrentiy.py`) in a background thread
2. Opens the dashboard in a pywebview native window pointed at `http://localhost:7878`
3. Adds a system tray icon with pystray

```
desktop.py responsibilities:
├── Import and start lavrentiy engine (background thread)
├── Wait for HTTP server to be ready (poll localhost:7878/api/state)
├── Open pywebview window → http://localhost:7878
├── System tray icon (pystray):
│   ├── "Show Dashboard" — bring window to front
│   ├── "Hide" — minimize to tray
│   └── "Quit" — clean shutdown (close window, stop engine, release mutex)
└── Handle window close → minimize to tray (don't exit)
```

**Critical details:**

- The engine (`lavrentiy.py`) runs as module-level code — it's not wrapped in `if __name__ == '__main__'`. You CANNOT `import lavrentiy` directly because the entire engine starts on import. Instead, run it in a subprocess or exec it in a thread. The cleanest approach:
  - Start `lavrentiy.py` as a subprocess (`subprocess.Popen([sys.executable, 'lavrentiy.py'])`)
  - The desktop wrapper is a SEPARATE process that launches the engine and then opens the window
  - On quit, send a kill signal to the engine subprocess

- The engine already has single-instance mutex enforcement. If `desktop.py` launches lavrentiy as a subprocess, the mutex will be held by that subprocess. `desktop.py` itself should NOT create the mutex.

- The engine prints to stdout/stderr. When running via `desktop.py`, capture or suppress this output (the engine already handles `sys.stdout is None` for pythonw mode).

- pywebview window should:
  - Title: "ЛАВРЕНТИЙ" (Cyrillic)
  - Size: 1100x750 (the dashboard is designed for this width)
  - Min size: 800x600
  - Background color: `#1a1a2e` (matches dashboard dark theme)
  - Resizable: yes
  - On close → hide to tray, don't quit
  - `webview.start(debug=False)` in production

- System tray icon:
  - Use `lavrentiy.ico` from the repo root (already exists)
  - Menu: Show Dashboard, separator, Quit
  - Left-click tray icon → show dashboard
  - Quit → kill engine subprocess, destroy window, exit

### 2. `desktop.bat` — New launch script

```batch
@echo off
start /B pythonw desktop.py
```

### 3. `requirements-desktop.txt` — New file

```
pywebview>=5.0
pystray>=0.19
Pillow>=10.0
```

(Pillow is required by pystray for icon handling)

### 4. Update `install.bat`

Add pywebview and pystray to the pip install step. Find the existing `pip install` line and add:
```
pip install pywebview pystray Pillow
```

### 5. Optional: `Lavrentiy Desktop.vbs` — Windows shortcut (silent launch)

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\georg\Documents\GitHub\lavrentiy"
WshShell.Run "pythonw desktop.py", 0, False
```

## What NOT to Change

- **Do not modify `lavrentiy.py`** — the engine stays exactly as-is
- **Do not modify `dashboard.html`** — the dashboard stays exactly as-is
- **Do not add Electron, Tauri, or any JS build toolchain**
- **Do not add a new web framework** (Flask, FastAPI, etc.) — the engine already has its own HTTP server
- **Do not change the hotkey system** — F9/F10/F11/F12 stay as keyboard hooks in the engine

## How to Test

1. Run `python desktop.py` from the repo root
2. Engine should start (you'll see "LAVRENTIY v0.1" in the console if running with `python` not `pythonw`)
3. After ~2-3 seconds, a native window should open showing the dashboard
4. The dashboard should show engine state (layer, tone, mode)
5. Close the window → it should minimize to system tray
6. Click tray icon → window should reappear
7. Right-click tray → Quit → everything shuts down cleanly
8. Verify no orphan `pythonw.exe` processes remain after quit

## Architecture Diagram

```
desktop.py (main process)
    │
    ├── subprocess.Popen(lavrentiy.py)  ← engine + HTTP server on :7878
    │       └── keyboard hooks (F9/F10/F11/F12)
    │       └── ThreadingHTTPServer(:7878)
    │             └── serves dashboard.html
    │             └── /api/* endpoints
    │
    ├── pywebview.create_window → http://localhost:7878
    │       └── native window showing dashboard
    │
    └── pystray.Icon (system tray)
            └── Show / Hide / Quit
```
