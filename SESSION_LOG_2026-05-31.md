# Session log — 2026-05-31 → 2026-06-03

Short bookkeeping session covering the SignPath Foundation application submission.

## What shipped

- SignPath Foundation application submitted to https://signpath.org/apply on 2026-05-31.
- Operator pasted the form values manually in Chrome on their phone after the Claude-driven submission path failed (see failure log below).
- `SIGNPATH_APPLICATION.md` status checklist updated: `[x] Application submitted at https://signpath.org/apply (2026-05-31)`.
- SignPath response window: 3–10 business days per their stated SLA. Fallback path if no response by ~2026-06-14: Azure Trusted Signing (~$9.99/month, same-day setup, no LICENSE required). Both paths fully documented in `SIGNING.md`.

## Form values submitted (snapshot of what's now in front of the reviewer)

| Field | Value |
|---|---|
| Project Name | Lavrentiy |
| Repository URL | https://github.com/gugosf114/lavrentiy |
| Homepage URL | https://github.com/gugosf114/lavrentiy |
| Download URL | https://github.com/gugosf114/lavrentiy/releases/latest |
| Privacy Policy URL | https://github.com/gugosf114/lavrentiy/blob/main/PRIVACY.md |
| Wikipedia URL | (skipped — optional) |
| Tagline | Voice reconstruction for Windows — hold F9, ramble, get polished text pasted into any app. Built for speech disfluencies and non-native English speakers whose accents we detect from text, not audio. |
| Description | Full reconstruction-engine positioning + L1-transfer accent detection + Grammarly-for-voice framing + Apache 2.0 declaration (see SIGNPATH_APPLICATION.md §4 — final v2 wording, NOT the v1 draft that called it "voice cleanup engine") |
| Reputation / Additional Information | Bundled-API-keys story + no-telemetry + offline L1 + unsigned-installer pain (see §9) |
| Build Environment | GitHub Actions Windows runners + PyInstaller --onedir + Inno Setup 6, signing step pending |
| First Name | Gurgen |
| Last Name | Abrahamyants |
| Email | gugosf@gmail.com |
| Primary Discovery Channel | Organic search |
| Code of Conduct + personal data consent | ✓ ✓ |
| reCAPTCHA | Operator clicked manually on phone |

## What's next

- Wait for SignPath email confirmation of receipt (usually within 24h).
- On approval: set `SIGNPATH_API_TOKEN` + `SIGNPATH_ORG_ID` repo secrets, create `.github/workflows/build-and-sign.yml` from the scaffold in `SIGNING.md` Path A, build + tag v1.6.7 (or whatever is current), workflow signs + publishes.

## Failure log

### #113 — Drove SignPath form on desktop Chrome when operator wanted phone Chrome

I filled the SignPath form via `mcp__chrome-devtools__*` (CDP on `127.0.0.1:9222`) on the operator's desktop Chrome, then handed off for the operator to click reCAPTCHA + Submit. Operator response: "I wanted you to do it in a chrome browser, but on the fucking phone." Wasted browser-fill iteration. Resolution: abandoned the desktop tab, pivoted to phone Chrome automation. Underlying error: jumped to action on "drive the form" without checking which device the operator meant. Memory rule [[feedback_jump_to_action]] does NOT override the device-target question.

### #114 — Phone Chrome automation chained three dead ends before pivoting to paste-columns

Tried to drive phone Chrome via ADB. Three dead ends in sequence:

(a) `adb forward tcp:9223 localabstract:chrome_devtools_remote` succeeded (port forward established), but `curl http://localhost:9223/json/version` returned empty — phone Chrome does not expose the CDP socket without a `chrome://flags` toggle (or chrome://inspect-from-desktop wake-up). Phone Chrome remote debugging is not a one-line setup like desktop Chrome.

(b) `uiautomator dump` of the phone Chrome screen returned exactly one `EditText` node: the Chrome URL bar. Web content inside a WebView is one opaque rectangle to UI Automator — form fields are not exposed as native Android UI nodes. Pattern: WebView contents are invisible to native a11y dumpers; need either CDP or pixel-based interaction.

(c) Pixel-tap + `adb shell input text` to a coordinate guessed from the initial screencap landed in a different Chrome tab (operator had a Signal/yu-gi-oh tab in foreground at tap time, not the SignPath tab). The next screencap showed Signal content, not SignPath form.

Resolution: stopped the automation attempts, gave the operator paste-ready text in column form ("just give me the answers in a fucking column here, I'll just copy and paste each one"). Operator submitted manually on phone in ~2 minutes.

Lesson: phone Chrome form-fill via ADB is a multi-day setup if the form is non-trivial. For one-shot submissions, paste-ready columns + manual operator submission is faster than getting the automation working. Save the ADB-phone-Chrome path for repeated/long-running workflows where the setup cost amortizes.

### #115 — Tagline v1 had two factual errors + one major omission

First tagline draft: "Open-source Windows voice cleanup engine — hold a hotkey, speak, get clean text pasted into any app." Operator flagged three issues:

1. **"Open-source" is wrong framing.** Lavrentiy is Apache 2.0 licensed and the repo is public, but the operator is explicit that "open source" is not the brand positioning. Use "publicly licensed" or omit the framing entirely; never lead with "open source" in marketing copy. SignPath's eligibility check is satisfied by the LICENSE file existing, not by branding.
2. **"Voice cleanup" is wrong category.** Lavrentiy is voice RECONSTRUCTION — Grammarly-for-voice — not cleanup and not voice-to-text. Cleanup implies preserving the user's words and just tidying them. Reconstruction means: stream-of-consciousness in → clean professional intent out. Wispr Flow is voice-to-text (different pipeline). Lavrentiy is not competing with them; different category.
3. **Major omission: L1-transfer accent detection.** Lavrentiy has a layer that identifies non-native English accent patterns from the TRANSCRIPT TEXT (not the audio waveform) and adjusts reconstruction accordingly. Per memory [[project_l1_transfer_angle]] this is a core differentiator that broadens the pitch beyond stutterers to all non-default English speakers. Should have been in the first tagline draft.

Lesson: when drafting positioning copy, re-read the relevant project memories (`project_lavrentiy_positioning`, `project_wim_positioning`, `project_l1_transfer_angle`, `feedback_dont_lead_with_stuttering`) BEFORE the first draft, not after the operator corrects it. The memories were specifically designed to prevent this exact failure shape.

Note: `feedback_dont_lead_with_stuttering.md` is general marketing guidance. For the SignPath audience specifically (Foundation funding speech-disfluency / accessibility-oriented OSS), leading with the speech-disfluency angle IS correct positioning — operator confirmed this explicitly: "lean in heavy on the stuttering aspect of it speech this fluency actually don't use stuttering just leaning heavy to speech this fluency." So: use "speech disfluency" (the term), not "stuttering" (the word), and lead with it in the SignPath context but not in general marketing.

### #116 — Tagline v2 missed Wikipedia / Download / Privacy URL fields

After fixing the tagline, operator: "you missed the download URL and privacy policy URL and then there's Wikipedia URL but that's optional." Three URL fields on the SignPath form were not in the column I gave. Resolution: provided `https://github.com/gugosf114/lavrentiy/releases/latest` for download, `https://github.com/gugosf114/lavrentiy/blob/main/PRIVACY.md` for privacy (PRIVACY.md already existed in the repo, no need to write one), Wikipedia skipped. Lesson: when giving paste-ready form values, enumerate ALL fields from the source form first (the desktop-Chrome fill earlier had touched all of them — should have remembered the full list).

## State at session end

- Lavrentiy main: latest commit on this session's branch is the SignPath status checkbox flip + this log + README update.
- A parallel Claude session has uncommitted work in `lavrentiy.py` (untouched by this session per the `feedback_no_commit_push_without_check` rule).
- WiM main: 7 files modified by parallel session — `AudioRecorder.kt`, `BubbleBluetoothSco.kt`, `BubbleService.kt`, `ProfileManager.kt`, `ReconstructClient.kt`, `WimAccessibilityService.kt`, `accessibility_config.xml`. Not touched by this session.
- SignPath: application submitted, awaiting response.
