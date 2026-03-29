# Privacy Policy

**Effective Date:** March 29, 2026
**Last Updated:** March 29, 2026

This Privacy Policy applies to **Лаврентий (Lavrentiy)** for Windows and **WiM — What I Meant** for Android (collectively, "the App"). WiM is powered by the Лаврентий voice reconstruction engine.

The App is developed by George Abrahamyants ("we," "us," "our").

---

## What the App Does

The App is a voice reconstruction tool that turns messy, real-world speech into clean, professional text. It captures speech via your device's microphone, transcribes it, reconstructs it into polished text matching your chosen tone, and pastes the result into the active application or text field. Whether you're dictating emails, taking meeting notes, or drafting messages on the go, the App delivers what you meant to say — not what the microphone heard.

The App includes advanced speech accessibility features — including disfluency detection, clinical reconstruction layers, and personalized learning informed by established speech science research (Brown, 1945; Ghai & Mueller, ASSETS 2021) — that make it particularly effective for users with speech disfluencies.

---

## What Data We Collect

### Voice Audio
Audio is captured from your microphone **only while you are actively recording** (you press a button to start and stop). Audio is streamed to the OpenAI Whisper API for transcription and is **not stored** by us. Once the transcription is returned, the audio is discarded. We do not record, save, or retain your voice audio.

### Transcription and Reconstruction Text
Your raw transcription (what the speech recognizer heard) and the reconstructed output (the cleaned text) are stored **locally on your device** in a session history database. This data does not leave your device unless you are signed in and using the cloud reconstruction service, in which case the text is sent to our backend server for processing and is not retained after the response is returned.

### Voice Profile
The App learns your speech patterns over time: vocabulary you use frequently, corrections the system makes repeatedly, words that trigger disfluency, and filler words. This profile data is stored **locally on your device** in a JSON file. It is not uploaded to our servers.

### Account Information
If you sign in with Google, we receive your email address, display name, and a unique identifier from Google/Firebase Authentication. This is used solely to identify your account and manage your subscription tier. We do not access your Google contacts, calendar, Drive, or any other Google service.

### Usage Metadata
We store basic session metadata locally on your device: timestamps, which tone and layer settings were used, word counts, and processing times. This data is used to display your session history and is not transmitted to any server.

---

## What Data We Do NOT Collect

- We do not record or store your voice audio
- We do not collect your location
- We do not collect your contacts
- We do not use cookies, tracking pixels, or advertising identifiers
- We do not fingerprint your device
- We do not sell or rent any data to anyone

---

## Third-Party Services

### OpenAI (Whisper API and GPT)
Voice audio is sent to OpenAI's Whisper API for transcription. Reconstructed text is generated using OpenAI's GPT models. Per OpenAI's API data usage policy (as of March 2025), **data sent through the API is not used to train OpenAI's models** by default. We do not opt in to any data sharing or training programs with OpenAI. For OpenAI's full privacy practices, see: https://openai.com/policies/privacy-policy

### Google Firebase (Authentication)
If you sign in with Google, authentication is handled by Firebase Authentication, a Google Cloud service. Firebase receives your Google account credentials to verify your identity. See Google's privacy policy at: https://policies.google.com/privacy

### Google Cloud Functions (Backend Proxy)
When you are signed in and using cloud reconstruction, your text (not audio) is sent to a Google Cloud Function that acts as a proxy to OpenAI. The text is processed in memory and is not stored. The Cloud Function verifies your identity, checks your subscription tier, and forwards the reconstruction request.

---

## Data Storage and Retention

| Data | Where Stored | Retention |
|------|-------------|-----------|
| Voice audio | Not stored | Discarded immediately after transcription |
| Session transcripts | Your device only | Until you delete them |
| Voice profile | Your device only | Until you delete it or delete the app |
| Account info (email) | Firebase | Until you delete your account |
| Cloud reconstruction text | Processed in memory | Not retained after response |

If you delete your account or uninstall the App, your local data (profile, session history) remains on your device until you manually delete the application folder. To request deletion of your Firebase account data, contact us at the address below.

We will not retain any of your personal information for longer than twelve (12) months after you delete your account or request data deletion.

---

## Data Sharing

We do not share your personal data with any third party except as described above (OpenAI for transcription/reconstruction, Firebase for authentication). We do not share data with advertisers, analytics services, data brokers, or any other entity.

---

## AI Model Training

**We do not use your data to train any AI model.** Your voice, transcriptions, profile data, and usage patterns are never used for machine learning training, by us or by any third party. OpenAI's API data usage policy confirms that API inputs and outputs are not used for model training by default, and we have not opted into any training data programs.

---

## Voice Profile and Biometric Data

The App builds a voice profile that includes vocabulary patterns, disfluency triggers, and learned corrections. This profile describes your **speech patterns**, not your **voice biometrics** (voiceprint, vocal frequency signature, or speaker identification features). The profile cannot be used to identify you by voice. It is stored locally on your device and is not transmitted to any server.

If you reside in a jurisdiction with biometric data laws (such as Illinois BIPA, Texas CUBI, or Washington state), please note that we do not collect, store, or process biometric identifiers or biometric information as defined by those laws.

---

## Children's Privacy

The App is not directed at children under 13. We do not knowingly collect personal information from children under 13. If you believe a child has provided us with personal information, contact us and we will delete it.

---

## Your Rights

You have the right to:
- **Access** your data — all profile and session data is stored locally on your device and is directly accessible to you
- **Delete** your data — delete the application folder to remove all local data; contact us to delete your Firebase account
- **Opt out** of cloud processing — use a local API key instead of signing in with Google; all processing stays on your device
- **Export** your data — your profile (JSON) and session history (SQLite) are standard file formats you can copy at any time

---

## Security

- Audio is transmitted to OpenAI over encrypted HTTPS connections
- Authentication tokens are transmitted over encrypted HTTPS connections
- Local data is stored in your user profile directory with standard operating system file permissions
- The Cloud Function backend does not log or store request or response bodies

---

## Changes to This Policy

We may update this Privacy Policy from time to time. Changes will be posted to this page with an updated "Last Updated" date. Continued use of the App after changes constitutes acceptance of the revised policy.

---

## Contact

For questions, data deletion requests, or concerns about this Privacy Policy:

**George Abrahamyants**
Email: gugosf@gmail.com
GitHub: https://github.com/gugosf114/lavrentiy

---

*This policy covers both Лаврентий (Lavrentiy) for Windows and WiM — What I Meant for Android. WiM is powered by the Лаврентий voice reconstruction engine.*
