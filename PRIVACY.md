# Lavrentiy Privacy Policy

**Effective date:** July 17, 2026

**Last updated:** July 17, 2026

This policy applies to Lavrentiy for Windows. It does not describe the separate WiM Android app.

Lavrentiy is developed by Gurgen Abrahamyants ("we," "us," or "our").

## What Lavrentiy does

Lavrentiy records speech when the user deliberately starts recording, converts captured audio to text, optionally reconstructs that text, and pastes the result into the active Windows application. It includes communication-assistance features for repetitions, pauses, substitutions, and other speech disfluencies. It is not a diagnostic or treatment service.

## Local data

Lavrentiy stores the following on the user's Windows computer:

- Raw transcriptions, reconstructed text, timestamps, settings, processing measurements, and session history.
- A profile containing vocabulary, confirmed corrections, fillers, trigger words, and other learned preferences.
- Session audio. Audio archiving is enabled by default and pauses when the configured local storage cap is reached (currently approximately 2 GB).
- Calibration recordings, corrected calibration transcripts, and any experimental synthetic test data the user chooses to generate.

Local profile data is normally under `%USERPROFILE%\.lavrentiy\profiles\`. It remains until the user deletes the profile, its files, or the application data.

## Local and cloud processing

Local English faster-whisper transcription is the default. In that path, transcription audio remains on the computer. The bundled local model is English-only; selecting another supported dictation language requires configured cloud transcription.

Cloud processing occurs only when the user selects or invokes a configured cloud feature:

- With a user-provided OpenAI key, audio may be sent directly to OpenAI for cloud transcription and text may be sent for reconstruction.
- With a configured Anthropic key, reconstruction text may be sent directly to Anthropic.
- When signed in with Google, cloud-transcription audio or reconstruction text and the context required for that request may be sent through the authenticated Google Cloud backend. The backend may then call an AI provider.

Lavrentiy cannot reconstruct words that were never captured in audio. Pause Bridge may generate optional completion suggestions from the text already captured; the user decides whether to use one.

## Google sign-in and profile sync

If the user signs in with Google, Firebase Authentication provides the account email address, display name, and unique account identifier. Lavrentiy does not request access to Google contacts, calendar, Drive, or Gmail.

Selected learned profile metadata may be synchronized to Firestore, including vocabulary, corrections, filler words, trigger words, phonetic weights, and avoidance-pair data. This supports use across devices and personalized backend reconstruction. Local session audio is not uploaded as part of profile sync; an individual recording is uploaded only when the user invokes configured cloud transcription.

## Third-party services

Depending on the features the user chooses, data may be processed by:

- OpenAI for cloud speech transcription or text reconstruction: <https://openai.com/policies/privacy-policy>
- Anthropic for text reconstruction: <https://www.anthropic.com/legal/privacy>
- Google Firebase and Google Cloud for authentication, profile synchronization, and authenticated backend processing: <https://policies.google.com/privacy>

Those providers process data under their own terms and policies. Lavrentiy does not promise that a third-party provider retains no operational logs; users should consult the linked provider policies.

## Data we do not intentionally collect

Lavrentiy does not request location, contacts, advertising identifiers, or access to unrelated Google services. We do not sell or rent user data and do not include advertising.

## Model training

Lavrentiy does not automatically upload local archived audio or calibration recordings for shared-model training. The local archive and corrected calibration set are retained so the user may later evaluate or train a personal speech model. Experimental synthetic samples are engineering data and are not represented as genuine stuttered-speech recordings.

Third-party AI providers govern their own processing and model-training practices under the policies linked above.

## Retention and deletion

| Data | Location | Retention |
|---|---|---|
| Session audio | User's computer | Until deleted or the local archive policy removes/pauses data |
| Calibration audio and transcripts | User's computer | Until deleted by the user |
| Session text and metadata | User's computer | Until the profile or application data is deleted |
| Local learned profile | User's computer | Until the profile or application data is deleted |
| Synced profile metadata | Firestore, after Google sign-in | Until the user deletes cloud data or requests account deletion |
| Account identifier and email | Firebase Authentication | Until account deletion |
| Cloud request audio or text | Selected cloud provider/backend | Subject to the applicable provider and service policies |

The Profile tab includes export and cloud-data deletion controls. Deleting cloud data does not automatically delete local files. Deleting the local profile does not automatically delete the Firebase Authentication account. Contact us for account deletion assistance.

## Security

Cloud requests use encrypted HTTPS connections. Local files use the permissions of the user's Windows account. No software or transmission method can be guaranteed completely secure.

## Children's privacy

Lavrentiy is not directed to children under 13. If you believe a child supplied personal information through a cloud account, contact us so it can be reviewed and deleted.

## Changes

We may update this policy as Lavrentiy changes. The current version and update date will remain in this repository.

## Contact

**Gurgen Abrahamyants**
Email: gugosf@gmail.com
GitHub: <https://github.com/gugosf114/lavrentiy>
