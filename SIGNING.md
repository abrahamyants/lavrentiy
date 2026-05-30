# Code signing — Lavrentiy installer

Lavrentiy installers are currently shipped **unsigned**. Every fresh download triggers Windows SmartScreen ("Windows protected your PC" — click "More info → Run anyway") on first launch. This document covers what's required to sign installers properly, the two viable paths, and the steps to take once a signing certificate is in hand.

## Why this matters

SmartScreen warnings are the single largest install-time friction point. Empirically, a non-trivial percentage of users abandon installation when they see the warning. Signing kills the warning permanently (after a brief reputation-build period for new signing certificates).

Code signing is unblocked since v1.6.2 (commit `22d9e75`) when the Apache 2.0 LICENSE landed at the repo root. Both viable paths require either a LICENSE (free path) or a recurring fee (paid path).

## Two paths

### Path A — SignPath Foundation (free, recommended)

[SignPath Foundation](https://signpath.org/foundation) provides free code signing certificates to qualifying open-source projects. Lavrentiy qualifies:

- Public OSS GitHub repository ✓
- LICENSE file at repo root (Apache 2.0) ✓
- Real active project with version history ✓
- Single maintainer (Gurgen Abrahamyants) — fine, no team requirement ✓

**Cost:** $0.
**Lead time:** typically 3–10 business days for application review and certificate issuance.
**Renewal:** annual, free, requires re-verification.
**Restriction:** can only sign builds from the public GitHub repository's CI (no local signing of arbitrary binaries) — by design, prevents abuse.

#### Application material (paste into SignPath's application form)

**Project name:** Lavrentiy

**Project URL:** `https://github.com/gugosf114/lavrentiy`

**License:** Apache 2.0 (see `LICENSE` at repo root)

**Project description (~100 words):**
> Lavrentiy is a Windows desktop voice-cleanup engine. Users hold a hotkey to record into their microphone; Lavrentiy transcribes via OpenAI Whisper, runs reconstruction through GPT-4o (and Claude Sonnet for clinical-grade work), and pastes the cleaned text into whatever app is in front of them. It handles fillers, false starts, run-on sentences, and speech disfluencies that voice typing tools normally ignore. Single-file Python engine + browser dashboard, distributed as an Inno Setup installer. Open-source under Apache 2.0; cross-device profile sync via Firebase.

**Maintainer name + email:** Gurgen Abrahamyants — gugosf@gmail.com

**Signing artifacts produced:** Inno Setup `.exe` installers (single artifact per release, ~524 MB)

**Build environment:** GitHub Actions Windows runners, PyInstaller `--onedir` + Inno Setup compile

**Notes for reviewers:** Project ships with bundled API keys for the developer's OpenAI and Anthropic accounts (the developer pays for everyday usage) plus a "bring your own key" override path in the dashboard. The installer does NOT collect or transmit any user telemetry; the engine runs locally and only calls external APIs when the user records audio.

#### Submission steps

1. Go to https://about.signpath.io/foundation
2. Click "Apply now"
3. Fill in the form with the material above
4. Wait for email confirmation of application receipt
5. Respond to any clarifying questions from the SignPath team
6. On approval: receive an integration project token + signing-policy ID

#### Once approved — GitHub Actions integration

SignPath provides a ready-made GitHub Action: `SignPath/GitHubActionTemplate`. The workflow scaffold below assumes their standard pattern.

```yaml
# .github/workflows/build-and-sign.yml
name: Build and Sign Installer

on:
  push:
    tags: ['v*']
  workflow_dispatch:

permissions:
  contents: write
  id-token: write

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install pyinstaller pywebview pythonnet faster-whisper openai anthropic sounddevice soundfile keyboard pyperclip pyautogui scipy onnxruntime metaphone
      - run: python -m PyInstaller Lavrentiy-onedir.spec --noconfirm --distpath dist-onedir --workpath build-onedir
      - name: Install Inno Setup
        run: choco install innosetup --no-progress
      - name: Compile installer
        run: '& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\Lavrentiy.iss'
      - uses: actions/upload-artifact@v4
        with:
          name: lavrentiy-installer-unsigned
          path: installer/Output/Lavrentiy-Setup-*.exe

  sign:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: lavrentiy-installer-unsigned
          path: ./
      - uses: SignPath/GitHubActionTemplate@v1
        with:
          api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
          organization-id: ${{ secrets.SIGNPATH_ORG_ID }}
          project-slug: lavrentiy
          signing-policy-slug: release-signing
          github-artifact-name: lavrentiy-installer-unsigned
          wait-for-completion: true
          output-artifact-directory: signed/
      - uses: actions/upload-artifact@v4
        with:
          name: lavrentiy-installer-signed
          path: signed/

  release:
    needs: sign
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/')
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: lavrentiy-installer-signed
          path: ./
      - uses: softprops/action-gh-release@v2
        with:
          files: Lavrentiy-Setup-*.exe
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Required GitHub repo secrets to populate after SignPath approval:
- `SIGNPATH_API_TOKEN`
- `SIGNPATH_ORG_ID`

Until those are set, the `sign:` job will fail and the workflow won't publish a release — the existing manual release flow (`gh release create v1.6.x installer/Output/...`) continues to work.

---

### Path B — Azure Trusted Signing (paid, fast)

If SignPath approval is too slow or rejected for any reason, Microsoft's Azure Trusted Signing service is the no-license, no-wait alternative.

**Cost:** ~$9.99/month per subscription.
**Lead time:** same day (after Azure subscription setup + identity verification, which typically takes hours).
**Restriction:** requires an Azure subscription + paying monthly. Signs any artifact you upload.

#### Setup steps

1. Create an Azure subscription if you don't have one (free tier exists, but Trusted Signing requires a paid plan or pay-as-you-go).
2. In the Azure Portal, navigate to "Trusted Signing Accounts" and create one (~$10/mo).
3. Verify your identity (Microsoft Entra individual or business identity proofing).
4. Create a Certificate Profile.
5. Install the `Azure.CodeSigning.Dlib` library.
6. Sign locally with `signtool.exe sign /dlib AzureCodeSigningDlib.dll /dmdf params.json installer/Output/Lavrentiy-Setup-v1.6.7.exe`.
7. Or use the same GitHub Actions integration via the `azure/trusted-signing-action@v0` action.

Azure docs: https://learn.microsoft.com/en-us/azure/trusted-signing/

---

## Recommendation

Apply to SignPath Foundation first. If approval lands within a week, take that path — it's free and the integration is straightforward. If 10 business days elapse without approval, fall back to Azure Trusted Signing.

Either way, the goal is the same: ship a signed installer so users stop hitting "Windows protected your PC" on first launch.

## What this does NOT cover

- macOS code signing (Lavrentiy is Windows-only currently — no Mac build, no Apple Developer ID needed)
- Linux package signing (not applicable)
- Android APK signing (handled separately in the wim-android repo via Android keystore, already in place for Play Store submission)
