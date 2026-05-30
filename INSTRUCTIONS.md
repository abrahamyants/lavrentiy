# Lavrentiy — User Instructions

For end users. If you're a developer working on Lavrentiy, see `README.md` instead.

## What Lavrentiy is

A desktop app for people whose speech doesn't come out clean — stuttering, blocks, fillers, word swaps. You hold F9, talk into your mic, and Lavrentiy turns your messy spoken words into the clean sentence you meant to say, then pastes it into whatever app is in front of you (email, Slack, browser, anywhere). It runs on Windows, sits quietly in your system tray, and gets smarter at understanding YOUR speech the more you use it.

---

## Download

Go to: **https://github.com/gugosf114/lavrentiy/releases/latest**

Click on `Lavrentiy-Setup-v1.6.4.exe` to download it. The file is about 520 MB — give it a minute or two depending on your connection.

That's the only file you need. There's no separate "trial" or "free" version. The download is the full app.

---

## Install

1. Double-click the downloaded `Lavrentiy-Setup-v1.6.4.exe`.

2. **You'll see "Windows protected your PC."** This is normal — the installer isn't code-signed yet (signing is on the to-do list). Click **More info → Run anyway**. This happens once. Future launches don't show the warning.

3. The installer runs through Welcome → Install → Finish like any normal Windows program. You'll see a checkbox for "Create a desktop shortcut" — leave it checked if you want a desktop icon.

4. **Install location**: `%LOCALAPPDATA%\Programs\Lavrentiy`. No admin rights needed — it installs just for your user account. Won't ask for your password.

5. When the installer finishes, the app launches automatically. If it doesn't, find "Lavrentiy" in your Start Menu.

---

## First launch — two shortcuts

After install, you'll see **two** Lavrentiy shortcuts in Start Menu:

- **Lavrentiy** — opens the dashboard in Chrome or Edge in app mode (chromeless — no URL bar, no tabs, looks like a normal Windows window).
- **Lavrentiy (Native)** — opens the dashboard in a bundled WebView2 window. No external browser involved.

Both do exactly the same thing visually. The difference is what's running underneath:

- The first uses whatever Chrome or Edge you already have installed.
- The second uses Microsoft's built-in WebView2 component (ships with Windows 10 and 11 by default).

**Pick whichever you like.** Most people use the first one. If you don't have Chrome or Edge installed for some reason, use the second.

---

## How to use it

1. Click the Lavrentiy shortcut. Engine starts, dashboard window opens.
2. Hold **F9** down while you talk into your microphone. Release F9 when you're done.
3. Wait 1–3 seconds. The cleaned-up version gets pasted into whatever app you have in front of you (the one with the typing cursor).

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

## Using your own API key (optional)

Lavrentiy comes with the developer's OpenAI and Anthropic API keys pre-loaded so you can use it immediately without setup. Your usage is billed against the developer's accounts.

If you have your own OpenAI / Anthropic accounts and prefer to bill against them:

1. Open the dashboard.
2. Find the **API key** field in the sidebar settings.
3. Paste your own key in.
4. Save.

After that, all your usage bills to your accounts, not the developer's. You can switch back to the bundled keys later by clearing your custom key.

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
- **First launch after install** — cold start. The engine loads a 500 MB speech recognition model the first time. Subsequent F9 presses are 1–3 seconds.
- **Cloud reconstruction is busy** — happens during peak hours when OpenAI / Anthropic queues are full. Wait, try again.
- **Very long recordings** — anything over 30 seconds takes proportionally longer. Try shorter bursts.

### "I signed in but my old learned data isn't there."

Make sure you're on **v1.6.4 or newer**. Earlier versions (v1.6.3 and below) had one-way cloud sync — they could push your profile up but couldn't pull it back. v1.6.4 fixes this.

If you're on v1.6.4 and still see an empty profile after sign-in:
- Check the engine log file at `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\engine_err.log` for any "Profile pull from cloud failed" messages.
- Wait 30 seconds, sign out, sign back in.

### "Sign-in popup never appears" / "Google auth doesn't work."

Google blocks OAuth inside embedded browsers, so Lavrentiy opens sign-in in your system default browser. If clicking Sign In does nothing:
- Make sure your default browser is set (Settings → Default apps → Web browser).
- Try copy-pasting `http://localhost:7878/auth/google` into your browser directly.

### "My API key was rejected."

For OpenAI: starts with `sk-` (project keys) or `sk-proj-` (newer format).
For Anthropic: starts with `sk-ant-`.

If you pasted one in the other slot, swap them. Check the key in OpenAI's / Anthropic's console isn't expired or revoked.

### "Engine is running but no window opens."

Sometimes the dashboard window fails to surface even when the engine is up. Fix:
- Right-click the Lavrentiy icon in the system tray (near the clock).
- Click "Open dashboard" or similar.

If there's no tray icon at all: end Lavrentiy.exe via Task Manager, then click the shortcut again.

---

## Uninstall

Settings → Apps → Installed apps → search "Lavrentiy" → click → Uninstall.

This removes the app but **leaves your profile data** at `C:\Users\<you>\.lavrentiy\`. If you want a truly clean wipe (lose all learned data), manually delete that folder after uninstalling.

If you signed in: your cloud-stored profile stays in your Firestore record even after uninstall. Reinstall + sign in = your profile comes back.

---

## Need help?

Email: **gugosf@gmail.com**

Please include:
- Which version of Lavrentiy (top of the dashboard, or check `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\VERSION.txt`).
- What you did, what you expected, what actually happened.
- Any error message text (full text, not a description).
- If the engine logged anything: contents of `%LOCALAPPDATA%\Programs\Lavrentiy\_internal\engine_err.log`.

Bug reports and feature requests can also go directly to:
**https://github.com/gugosf114/lavrentiy/issues**

(Requires a free GitHub account.)
