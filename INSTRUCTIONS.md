# Lavrentiy — User Instructions

For end users. If you're a developer working on Lavrentiy, see `README.md` instead.

## What Lavrentiy is

A Windows voice-to-intent app for everyday dictation. It transcribes captured audio, can clean recognizable fillers and repetitions, optionally reconstructs the transcript using personal context, and pastes the result into the active application. It is designed to remain usable when speech contains long pauses, substitutions, repetitions, or blocks.

Lavrentiy does **not** diagnose a speech condition, measure clinical severity, or recover a word that was never captured. Pause Bridge can offer optional sentence completions from the words already transcribed; the user chooses whether to use one.

---

## Download

Go to: **https://github.com/gugosf114/lavrentiy/releases/latest**

Click `Lavrentiy-Setup-v1.7.0.exe`. The installer is large because it includes the local speech-recognition model.

That's the only file you need. There's no separate "trial" or "free" version. The download is the full app.

---

## Install

1. Double-click `Lavrentiy-Setup-v1.7.0.exe`.

2. **You'll see "Windows protected your PC."** This is normal — the installer isn't code-signed yet (signing is on the to-do list). Click **More info → Run anyway**. This happens once. Future launches don't show the warning.

3. The installer runs through Welcome → Install → Finish like any normal Windows program. You'll see a checkbox for "Create a desktop shortcut" — leave it checked if you want a desktop icon.

4. **Install location**: `%LOCALAPPDATA%\Programs\Lavrentiy`. No admin rights needed — it installs just for your user account. Won't ask for your password.

5. When the installer finishes, the app launches automatically. If it doesn't, find "Lavrentiy" in your Start Menu.

---

## First launch

The installer creates one **Lavrentiy** shortcut. It opens the dashboard in a normal Windows application window. The first start may be slower while Windows and the local speech model initialize.

---

## How to use it

1. Click the Lavrentiy shortcut. Engine starts, dashboard window opens.
2. Either hold **F9** while speaking and release when finished, or click **idle** once to begin and again to stop.
3. Lavrentiy transcribes and processes the recording, then pastes the selected result wherever the typing cursor was. Processing time depends on the recording length, computer, and layer.

Other hotkeys live in the dashboard sidebar — F10 cycles tone (casual / professional / friend / formal), F11 cycles layer, F12 prints stats.

---

## Signing in (optional but recommended)

Sign-in with your **Google account** unlocks two things:

1. **Cross-device profile sync.** Lavrentiy learns your speech patterns over time — words you stutter on, sounds you struggle with, words you swap to avoid hard ones. Without sign-in, that learning lives only on the computer you used it on. Reinstall or switch machines and you start over.
2. With sign-in, your learned profile syncs to the cloud automatically. Sign in on a new machine and within seconds your trigger words and learned patterns appear in the dashboard.

How to sign in:
- Open the dashboard.
- Click the **Sign in** button in the top right (or wherever it appears).
- Your default browser will open with a Google sign-in page. Pick your account.
- You'll be redirected back to Lavrentiy. The dashboard now shows your profile name where the Sign In button was.

**Note:** sign-in is Google only right now. Microsoft, Apple, plain email/password are not wired up yet.

---

## Free local mode and cloud access

Local Layer 1 transcription works without an API key and is the default. Lavrentiy does **not** include the developer's private API keys.

For cloud reconstruction, click **Cloud setup / API key** below the sign-in button. Either sign in with an invited Google account or enter your own OpenAI key. A user-provided key is stored locally at `%USERPROFILE%\.lavrentiy\api_key.txt` and its usage is billed by OpenAI to that user.

---

## Common problems

### "Nothing happens when I click the shortcut."

The engine might already be running in the background. Look in your system tray (bottom-right of the taskbar, near the clock) for the Lavrentiy icon. Right-click it → check the menu.

If no tray icon either: open Task Manager (Ctrl+Shift+Esc), look for `Lavrentiy.exe`. If it's there, end the task, then try the shortcut again.

If it still doesn't open: see "Engine won't start" below.

### "SmartScreen says my computer is protected from this app."

Normal for unsigned software. Click **More info → Run anyway**. Once.

### "Engine won't start" / "Connection refused" / blank dashboard

The engine needs to bind to port 7878 to talk to the dashboard. If another program is already using that port, the engine won't start.

Fix:
1. Open PowerShell.
2. Run: `netstat -ano | findstr :7878`
3. If something shows up, note the last number (the PID).
4. Open Task Manager → Details tab → find that PID → End task.
5. Try the Lavrentiy shortcut again.

If the dashboard opens but says "Connection lost" with no other errors: close the dashboard, wait 10 seconds, click the shortcut again. The engine may still be starting (cold-start takes 10–30 seconds on first run after install).

### "My microphone isn't working."

Lavrentiy uses Windows' default audio input. Check:
1. Windows Settings → System → Sound → Input. Confirm the right microphone is selected as default.
2. Settings → Privacy & security → Microphone. Make sure "Let apps access your microphone" is ON and "Lavrentiy" or "Desktop apps" is allowed.

Test the mic by recording yourself in Windows Voice Recorder first. If that works but Lavrentiy still doesn't pick up audio, restart Lavrentiy.

### "Reconstruction is really slow."

Three causes:
- **First transcription after each app start** — the bundled speech model must load into memory. Later recordings in that session are usually faster; exact time depends on the computer and recording length.
- **Cloud reconstruction is busy** — cloud-provider or network delays can vary. Wait briefly and try again.
- **Very long recordings** — anything over 30 seconds takes proportionally longer. Try shorter bursts.

### "I signed in but my old learned data isn't there."

Make sure you're on **v1.7.0 or newer**.

If you're on v1.7.0 and still see an empty profile after sign-in:
- Check the engine log file at `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\engine_err.log` for any "Profile pull from cloud failed" messages.
- Wait 30 seconds, sign out, sign back in.

### "Sign-in popup never appears" / "Google auth doesn't work."

Google blocks OAuth inside embedded browsers, so Lavrentiy opens sign-in in your system default browser. If clicking Sign In does nothing:
- Make sure your default browser is set (Settings → Default apps → Web browser).
- Try copy-pasting `http://localhost:7878/auth/google` into your browser directly.

### "My API key was rejected."

OpenAI keys normally start with `sk-` or `sk-proj-`. Check that the key is active and has API credit.

### "Engine is running but no window opens."

Sometimes the dashboard window fails to surface even when the engine is up. Fix:
- Right-click the Lavrentiy icon in the system tray (near the clock).
- Click "Open dashboard" or similar.

If there's no tray icon at all: end Lavrentiy.exe via Task Manager, then click the shortcut again.

---

## Uninstall

Settings → Apps → Installed apps → search "Lavrentiy" → click → Uninstall.

This removes the app but **leaves your profile, session text, archived audio, and calibration data** at `C:\Users\<you>\.lavrentiy\`. Delete that folder afterward only if you want a complete local wipe.

If you signed in: your cloud-stored profile stays in your Firestore record even after uninstall. Reinstall + sign in = your profile comes back.

---

## Need help?

Email: **gugosf@gmail.com**

Please include:
- Which version of Lavrentiy (shown during startup and in the installer filename).
- What you did, what you expected, what actually happened.
- Any error message text (full text, not a description).
- If the engine logged anything: contents of `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\engine_err.log`.

Bug reports and feature requests can also go directly to:
**https://github.com/gugosf114/lavrentiy/issues**

(Requires a free GitHub account.)
