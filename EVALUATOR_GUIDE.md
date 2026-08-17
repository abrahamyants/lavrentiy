# Lavrentiy V1 — Researcher Test Guide

## What it is

Lavrentiy is a Windows voice-to-intent application. It records only when the user starts recording, transcribes speech locally by default, can reconstruct the captured text with personal/contextual information, and pastes the result into the active application.

It is designed to remain usable when speech includes repetitions, substitutions, long pauses, or blocks. It is not a diagnostic or treatment tool and does not recover words that were never captured.

Lavrentiy was created by Gurgen Abrahamyants, a political refugee from Armenia who arrived in the United States without speaking English and lives with a speech block and a strong accent. He built it from his own daily communication needs, then expanded it for others who may face similar friction.

## Install

1. Download **`Lavrentiy-Setup-v1.7.6-eval.exe`** from <https://github.com/abrahamyants/lavrentiy/releases/latest>.
   This is the evaluation build. Every layer works on installation, with no
   account, no API key, and nothing to pay. The plain `Lavrentiy-Setup-v1.7.6.exe`
   on the same page is the standard build and will ask you to sign in.
2. If Windows shows **Windows protected your PC**, select **More info → Run anyway**. V1 is not code-signed.
3. Complete the installer and open the single **Lavrentiy** shortcut.

On an organization-managed computer, local policy may block unsigned applications. In that case, use a personal Windows computer or ask the organization's IT team to review the installer.

## Five-minute test

1. Open Notepad, email, or another application and place the typing cursor where text should appear.
2. In Lavrentiy, choose Layer 1.
3. Hold **F9** while speaking, then release. Alternatively, click **idle** once to start and again to stop.
4. Confirm that the transcription appears in the original application.
5. Try a sentence with a repetition, correction, or long pause.
6. Compare Layer 1 against Layer 2. Layer 1 writes down what was said; Layer 2
   writes down what was meant. That difference is the thing worth judging.
7. Switch **Tone** between Casual and Professional on the same sentence.
8. Try **Prep** with a name or technical phrase you plan to say.
9. Open the **Profile** tab and turn on **Stutter Support** to enable trigger
   learning, onset weighting, and covert-avoidance scoring. **DAF** with an
   adjustable delay is in the left rail.

## Important behavior

- The evaluation build needs no account and no API key on any layer. It carries
  its own credentials and allows 300 cloud requests per month per installation.
  After that, Layer 1 continues to work offline.
- Layer 1 transcribes on your own machine. Audio does not leave the computer on
  that layer. Layers 2 to 4 send the transcript, not the recording, to a
  reconstruction model.
- The bundled local model is English-only. Other dictation languages use cloud
  transcription, which the evaluation build also covers.
- **EN / RU** changes the interface language. The separate first-language packs apply only to English reconstruction on Layer 2 or 3; they are not transcription languages or a clinical accent assessment.
- SAFE mode protects a limited set of meaning anchors: names, numbers, dates, amounts, and negation. It is not a guarantee of semantic equivalence.
- Pause Bridge offers optional sentence completions based on captured context. It does not detect the content of a silent block.
- Session audio and calibration audio are stored locally by default. See [PRIVACY.md](PRIVACY.md).

## Feedback requested

Please report:

1. Did installation and first launch work without assistance?
2. Did both hold-to-talk and click-to-talk behave as expected?
3. Did text reach the intended Windows application?
4. Which speech patterns produced incorrect transcription or reconstruction?
5. Did the reconstructed version preserve names, numbers, dates, amounts, and negation?
6. Was the Basic screen understandable without opening Advanced?
7. Would this workflow help in real communication, and in which situation?

Send feedback and, if comfortable, anonymized raw/reconstructed examples to **gugosf@gmail.com** or open an issue at <https://github.com/abrahamyants/lavrentiy/issues>.
