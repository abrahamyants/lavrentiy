# SignPath Foundation Application — Lavrentiy

**Submit at:** https://about.signpath.io/foundation → "Apply now"

Each section below corresponds to a field in SignPath's application form. Copy each block into the matching field, hit submit, wait for their email.

---

## 1. Project name

```
Lavrentiy
```

## 2. Project URL

```
https://github.com/gugosf114/lavrentiy
```

## 3. License

```
Apache License 2.0
```

(See `LICENSE` at the repo root — landed in v1.6.2, commit `22d9e75`.)

## 4. Project description

```
Lavrentiy is an open-source Windows desktop voice-cleanup engine. Users hold a hotkey (F9) to record into their microphone; Lavrentiy transcribes the audio via OpenAI Whisper, runs reconstruction through GPT-4o or Claude Sonnet 4.6 with extended thinking, and pastes the cleaned-up text into whatever application the user has focused (email client, Slack, browser, text editor, etc.). It handles fillers, false starts, run-on sentences, and other speech disfluencies that regular voice typing tools leave in. A single-file Python engine plus a browser-based dashboard, distributed as an Inno Setup installer. The project ships with bundled API keys for the developer's OpenAI and Anthropic accounts (everyday usage is on the developer's tab) plus a "bring your own key" override path for users who want their own billing. Cross-device profile sync via Firebase. License is Apache 2.0.
```

## 5. Maintainer name + email

```
Gurgen Abrahamyants
gugosf@gmail.com
```

## 6. Signing artifacts produced

```
Inno Setup .exe installer (single artifact per release, ~524 MB compressed). Filename pattern: Lavrentiy-Setup-vX.Y.Z.exe
```

## 7. Build environment

```
GitHub Actions Windows runners. PyInstaller --onedir bundles the Python engine + dependencies + bundled offline speech recognition model + dashboard HTML/CSS/JS into dist-onedir/Lavrentiy/. Inno Setup 6 compiles the dist directory into a single .exe installer via installer/Lavrentiy.iss.
```

## 8. Release cadence

```
Roughly weekly during active development. Most recent releases: v1.5.7 (May 1), v1.6.0–v1.6.7 (early-to-mid May with multiple patch releases as audit findings were closed).
```

## 9. Reviewer notes (use the "additional information" field)

```
- Repository has been public since April 2026; private during early development.
- Project ships with bundled API keys for the developer's own paid OpenAI and Anthropic accounts so users can install and run without sign-up. Users can override with their own keys via the dashboard's API key field; user-supplied keys are stored only in the user's local install directory (api_key.txt and anthropic_key.txt, both gitignored).
- The installer does NOT collect or transmit telemetry. The engine runs locally and only calls external APIs (OpenAI Whisper + GPT-4o, Anthropic Sonnet, Google Firebase Auth + Firestore for optional cross-device profile sync) when the user records audio or signs in.
- Bundled offline speech recognition model (faster-whisper small.en, ~500 MB) means Layer 1 transcription works without internet when the user toggles to local mode.
- v1.6.x releases are unsigned currently — every fresh install triggers Windows SmartScreen "Windows protected your PC" warning. Code signing through SignPath Foundation would close this UX gap.
```

---

## After submission

1. SignPath will email confirmation of receipt within 24 hours.
2. They may follow up with clarifying questions about the project, the license, or the build environment. Respond to those.
3. On approval (typically 3–10 business days), you'll receive:
   - An organization ID
   - A project token (API token)
   - Signing policy slug (probably `release-signing`)
4. Add these as repo secrets in GitHub:
   - `SIGNPATH_API_TOKEN` (the project token)
   - `SIGNPATH_ORG_ID` (the organization ID)
5. Then create `.github/workflows/build-and-sign.yml` using the scaffold in `SIGNING.md` (Path A section). Push the workflow file, tag a new release, and the workflow will build + sign + publish automatically.

After the first signed release lives in the wild for a few weeks, Windows builds reputation for the signing certificate and SmartScreen stops warning entirely on subsequent downloads.

---

## If SignPath rejects or takes too long

Fall back to **Azure Trusted Signing** — ~$9.99/month, same-day setup, no LICENSE requirement. Full instructions in `SIGNING.md` Path B section.

---

## Status

- [x] Apache 2.0 LICENSE in place (v1.6.2)
- [x] Application material drafted (this file)
- [x] Application submitted at https://signpath.org/apply (2026-05-31)
- [ ] Approval received from SignPath team
- [ ] `SIGNPATH_API_TOKEN` + `SIGNPATH_ORG_ID` secrets added to GitHub repo
- [ ] `.github/workflows/build-and-sign.yml` created from SIGNING.md scaffold
- [ ] First signed release published
