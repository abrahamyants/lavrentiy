# Lavrentiy — User Instructions

For end users. If you're a developer working on Lavrentiy, see `README.md` instead.

## What Lavrentiy is

A Windows voice-to-intent app for everyday dictation. It transcribes captured audio, can clean recognizable fillers and repetitions, optionally reconstructs the transcript using personal context, and pastes the result into the active application. It is designed to remain usable when speech contains long pauses, substitutions, repetitions, or blocks.

Lavrentiy does **not** diagnose a speech condition, measure clinical severity, or recover a word that was never captured. Pause Bridge can offer optional sentence completions from the words already transcribed; the user chooses whether to use one.

---

## Download

Go to: **https://github.com/gugosf114/lavrentiy/releases/latest**

Click `Lavrentiy-Setup-v1.7.3.exe`. The installer is large because it includes the local English speech-recognition model.

That's the only file you need. There's no separate "trial" or "free" version. The download is the full app.

---

## Install

1. Double-click `Lavrentiy-Setup-v1.7.3.exe`.

2. **You may see "Windows protected your PC."** The installer is not code-signed. Click **More info → Run anyway**. Windows may show this again for a future unsigned installer version; ordinary app launches normally do not show it.

3. The installer runs through Welcome → Install → Finish like a normal Windows program. "Create a desktop shortcut" is optional and unchecked by default; select it if you want one. A Start Menu shortcut is always created.

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

Other hotkeys live in the dashboard sidebar — F10 cycles tone (casual / professional / friend / formal), F11 cycles layer, and F12 prints stats.

## Languages: three separate settings

Lavrentiy has three language systems. They do different jobs:

1. **Interface language:** use **EN / RU** above the main status ring. This changes the dashboard and built-in guide between English and Russian. Newly rewritten help text may fall back to English rather than show an outdated translation.
2. **Dictation language:** the language you actually speak. The bundled local model is **English-only**. Russian, Spanish, Portuguese, French, Arabic, German, Hindi, Italian, Japanese, Korean, and Mandarin use Cloud transcription and require Google sign-in or your own OpenAI API key.
3. **First-language transfer pack:** used only when you are speaking **English** on Layer 2 or 3. Ten optional packs—Russian, Spanish, Mandarin, Hindi, Arabic, Farsi, French, German, Korean, and Japanese—help reconstruction account for common first-language transfer patterns. This is personalization, not accent diagnosis, accent removal, or a different transcription language.

---

## Signing in (optional but recommended)

Sign-in with your **Google account** unlocks two things:

1. **Cross-device profile sync.** Confirmed vocabulary, corrections, and saved profile information can sync instead of remaining only on one computer.
2. **Authenticated cloud access.** Cloud transcription and reconstruction can use the server-side account path without placing a developer API key in the installer.

How to sign in:
- Open the dashboard.
- Click **Sign in** in the left sidebar.
- Your default browser will open with a Google sign-in page. Pick your account.
- You'll be redirected back to Lavrentiy. The dashboard now shows your profile name where the Sign In button was.

**Note:** sign-in is Google only right now. Microsoft, Apple, plain email/password are not wired up yet.

---

## Free local mode and cloud access

English Layer 1 transcription works locally without an API key and is the default. The bundled `small.en` model cannot transcribe the other listed languages. Lavrentiy does **not** include the developer's private API keys.

For non-English transcription or cloud reconstruction, click **Cloud setup / API key** below the sign-in button. Either sign in with an invited Google account or enter your own OpenAI key. A user-provided key is stored locally at `%USERPROFILE%\.lavrentiy\api_key.txt`; OpenAI bills that key's owner for its use.

---

## Common problems

### "Nothing happens when I click the shortcut."

The normal native-window shortcut does not create a tray icon. Open Task Manager (Ctrl+Shift+Esc), look for `Lavrentiy.exe`, end it if present, then try the shortcut again.

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

Make sure you're on **v1.7.3 or newer**.

If you're on v1.7.3 and still see an empty profile after sign-in:
- Check `%USERPROFILE%\.lavrentiy\engine_err.log` for any "Profile pull from cloud failed" messages.
- Wait 30 seconds, sign out, sign back in.

### "Sign-in popup never appears" / "Google auth doesn't work."

Google blocks OAuth inside embedded browsers, so Lavrentiy opens sign-in in your system default browser. If clicking Sign In does nothing:
- Make sure your default browser is set (Settings → Default apps → Web browser).
- Try copy-pasting `http://localhost:7878/auth/google` into your browser directly.

### "My API key was rejected."

OpenAI keys normally start with `sk-` or `sk-proj-`. Check that the key is active and has API credit.

### "Engine is running but no window opens."

Sometimes the dashboard window fails to surface even when the engine is up. Open `http://localhost:7878/` in your normal browser. If that does not open the dashboard, end `Lavrentiy.exe` in Task Manager and click the shortcut again. Native-window startup details are recorded in `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\native_boot.log`.

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
- If the engine logged anything: contents of `%USERPROFILE%\.lavrentiy\engine_err.log` and `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\native_boot.log`.

Bug reports and feature requests can also go directly to:
**https://github.com/gugosf114/lavrentiy/issues**

(Requires a free GitHub account.)
