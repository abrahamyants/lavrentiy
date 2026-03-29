# Privacy Policy Competitive Research
## For Лаврентий (Lavrentiy) + WiM (What I Meant)
### Compiled 2026-03-29

Research into how competitor voice/speech/clinical apps handle privacy, specifically
the clauses relevant to a stuttering-assistance app that:
1. Sends voice data to OpenAI for transcription/reconstruction
2. Stores profile data locally
3. Stores session history locally
4. Uses Firebase Auth

---

## 1. OTTER.AI

**Source:** https://otter.ai/privacy-policy

### Data Collection (Audio, Transcripts, Metadata)

> "Audio recordings, automatic OtterPilot screenshots and any text, images or videos"

> "You may provide us with your audio recordings...that you upload or provide to us in the context of the Services."

OtterPilot automatically captures screenshots during virtual meetings. They also collect:
- IP address, UUIDs, device IDs, web beacons, device information (carrier type, device model, operating system)
- Timestamps of access/record/edit/delete events

### Where Data Is Processed

> "Cloud service providers who we rely on for compute and data storage, including Amazon Web Services, based in the United States"

All cloud-based. No on-device processing mentioned. Data transfers to U.S. servers via AWS.

### Data Retention

> "Otter.ai stores all Personal Information for as long as necessary to fulfill the purposes set out in this Policy, or for as long as we are required to do so by law"

No specific timeframe. On deletion:
> measures to render such Personal Information "irrecoverable or irreproducible"

### AI Model Training

> "We obtain explicit permission (e.g. when you rate the transcript quality and check the box) for manual review of specific audio recordings to further refine our model training data"

They train on de-identified recordings and transcriptions containing Personal Information — but require user consent. Unless you're on an enterprise plan with contractual guarantees, meeting transcripts and audio may be analyzed to enhance AI performance.

### HIPAA Compliance

Otter.ai achieved HIPAA compliance in **July 2025** via independent assessment. Key details:

- **Enterprise plan ONLY.** Basic, Pro, and Business plan users cannot obtain a BAA and cannot use Otter for PHI.
- BAA available by contacting sales team.
- Builds on existing SOC 2 Type II certification.

CEO Sam Liang stated:
> "Achieving HIPAA compliance means that healthcare users will be able to confidently rely on Otter."

Safeguards announced:
> "Implementation of advanced encryption protocols and secure data storage solutions to protect PHI"
> "Strict access management to ensure that only authorized personnel can access sensitive information"
> "Ongoing training programs to ensure all team members are well-versed in HIPAA regulations"
> "Continuous monitoring and evaluation of Otter systems to maintain compliance and identify areas for improvement"

**Note:** The base privacy policy at otter.ai/privacy-policy contains NO HIPAA language. HIPAA is handled via separate BAA and enterprise agreement.

**Legal risk:** A putative class action (Brewer v. Otter.ai, Aug 2025) alleges OtterPilot recorded private conversations without proper consent.

### Data Deletion Rights

> "You have the right to request for your Personal Information to be erased or deleted"

Contact support@otter.ai. No automatic deletion timeline.

### Third-Party Sharing

Named recipients:
- Amazon Web Services (cloud storage)
- Amplitude (user analytics)
- Google LLC / Google Analytics (analytics)
- Stripe (payment processing)
- AppsFlyer (advertising tracking)
- Facebook/Meta (advertising partners)
- Data labeling service providers
- Law enforcement when legally required

> "We share your Personal Information with selected third parties"

---

## 2. DOXY.ME

**Sources:**
- https://doxy.me/en/privacy-policy (rendered as Framer CSS — policy text not extractable via fetch)
- https://help.doxy.me/en/articles/95911-security-and-privacy-overview
- https://help.doxy.me/en/articles/95854-is-doxy-me-hipaa-compliant

### Data Collection

**For Patients:** Doxy.me does not collect patient data. Patients do not need accounts.

**For Providers:** Email address, first name, last name. Optional: specialty, position/title, NPI, states licensed, mobile number, country.

**Critical clause — no recording:**
> "Doxy.me does not record any video or audio calls or save any chat messages at any time for any reason."
> "The session is never recorded or otherwise stored. It happens in real-time."

**File transfers:**
> "any photo or file transferred is automatically and permanently deleted after 15 minutes."

### Where Data Is Processed

> "All doxy.me data are stored within the highly secure Amazon Web Services (AWS) datacenter infrastructure."

### Encryption

- Video/audio: "point-to-point NIST-approved AES 128 bit encryption"
- Data at rest: "full volume encryption and AES 256-bit standard encryption"
- Interface: "secured over TLS 1.2+ (https)"
- Storage: "Amazon Web Services EBS encryption backed by an FIPS 140-2 key management infrastructure"

### Data Retention

No explicit retention periods documented. File transfers auto-delete after 15 minutes.

### AI Model Training

No mention of using any data for model training. Doxy.me is a real-time telehealth platform that explicitly does not store session content.

### HIPAA Compliance

**Full HIPAA/HITECH compliance.** Both free and paid versions.

> Doxy.me "will sign a Business Associates Agreement acknowledging us as a Business Associate."

BAA is available in the provider's account dashboard:
> "Sign the Business Associates Agreement found within your account dashboard"

> "annual HIPAA audits and reviews" with independent auditors
> "regular penetration testing"
> "baseline configurations recommended by industry standard CIS Benchmarks and Security Content Automation Protocol (SCAP)"

**Vendor BAAs:**
> "Vendors that assist in providing the Doxy.me platform have signed BAAs with doxy.me."
> "any data they receive from us will only be used for the purpose intended"
> "No data sent to a third-party will ever be sold."

### Third-Party Sharing

> Doxy.me "does not share or sell data to third parties."
> "any data they receive from us will only be used for the purpose intended"

Stripe handles payments:
> "certified as a PCI Level 1 Service Provider"
> Doxy.me "does not have access to customers' credit card data."

All vendors have signed BAAs.

---

## 3. SPEECHIFY

**Sources:**
- https://speechify.com/privacy/ (main consumer app)
- https://speechify.com/studio-privacy/ (Studio/voice clone product)
- https://speechify.com/terms-ai-voice-api/ (AI Voice API terms)

### Data Collection (Main App)

**User-Provided:**
> "username, email address, and contact and language preferences"
> Payment information for paid customers
> User Content (text, documents, or other content uploaded/transmitted)
> "Names of user contacts in Speechify Keyboard (on-device storage only)"

**Automatically Collected:**
> Location (IP address), log data (IP, browser type, date/time, language, cookies), usage information, device data, cookies, tracking pixels

**Sensory Information:**
> "Sensory information (such as audio recordings if you call our customer service)"

### Data Collection (Studio / Voice Clone)

> "We collect personal information that you voluntarily provide to us when you register on the Services" including "voice samples" and "Audio samples uploaded by you to our Services."

> "Sample history. Audio samples generated by you using our Services"

**Key classification clause:**
> "No. Although you can upload voice samples to our Service, those samples are not sensitive data because we do not use them for the purposes of identifying you."

### Where Data Is Processed

> "Information submitted to Speechify will be transferred to, processed, and stored in the United States."

Hybrid model:
> "User Content you save will be stored locally on that device and synced with our servers."
> "Names of user contacts in Speechify Keyboard" are "stored solely on your device...never sent to Speechify servers."

International transfers use Standard Contractual Clauses for EEA/UK/Swiss users.

### Data Retention

**Main app:**
> "we may keep some of your Personal Data for as long as reasonably necessary for our legitimate business interests, including fraud detection and prevention and to comply with our legal obligations."

No specific timeframe.

**Studio:**
> "We keep your information for as long as necessary to fulfill the purposes outlined in this Privacy Policy unless otherwise required by law"
> "No purpose in this Privacy Policy will require us keeping your personal information for longer than twelve (12) months past the termination of the user's account."

The 12-month cap on Studio is notable — concrete and borrowable.

### AI Model Training

**Main app:**
> "to improve our algorithms as described in the User Content section of our Terms of Service"
> "User Content you submit...may be viewed...to improve our algorithms"

**AI Voice API:**
> Explicitly prohibits customers from using the service to "generate synthetic training data for the creation of AI Voice Models"

Speechify retains the right to use Voice Materials to "generate the Synthetic Output." The underlying AI models remain Speechify's IP:
> "AI Voice Service including all underlying Speechify models, are part of the AI Voice Service and Speechify's intellectual property."

### HIPAA Compliance

**None.** No HIPAA language in any Speechify policy.

### Data Deletion Rights

**Main app:**
> "You can remove your Personal Data from Speechify at any time by logging into your account, accessing the Settings page, and then deleting your account."
> "For security reasons, subscribers of our paid services will first be instructed to cancel their subscriptions before they can delete their Speechify account."

**Studio:**
> Users can "request access and obtain a copy of your personal information, (ii) to request rectification or erasure" and have "the right to withdraw your consent at any time."

### Third-Party Sharing

**Named services:**
Google Analytics, Segment, Amplitude, Meta Pixel, Hotjar, Visual Website Optimizer, Intercom, Customer.io, Google Optimize 360, Bing Universal Event Tracking, TikTok Conversion Tracking Pixel

> "Speechify does not sell or rent your Personal Data."

**Studio:**
> Third-party vendors "cannot do anything with your personal information unless we have instructed them to do it."

---

## 4. GOOGLE CLOUD SPEECH-TO-TEXT

**Sources:**
- https://docs.cloud.google.com/speech-to-text/docs/data-logging
- https://docs.cloud.google.com/speech-to-text/docs/v1/data-usage-faq
- https://cloud.google.com/speech-to-text/docs/data-logging-terms
- https://cloud.google.com/security/compliance/hipaa

### Data Collection

**Default (no opt-in):**
> "When you send audio to the Cloud Speech-to-Text API streaming or sync endpoints, Google processes it in memory and does not store any customer data."

For async endpoints:
> "the resulting transcript is stored for a period of approximately 5 days"
> "The input audio data is not stored by the Cloud Speech-to-Text API service."

**Metadata always logged:**
> "Google temporarily logs some metadata about your Cloud Speech-to-Text API requests (such as the time the request was received and the size of the request) in order to improve our service and combat abuse."

### Where Data Is Processed

Cloud-based on Google infrastructure. Processing occurs in-memory for streaming/sync endpoints.

### Data Retention

**Without opt-in:** Audio not stored. Async transcripts ~5 days. Metadata temporarily logged.

**With data logging opt-in:**
> Google may "retain the Customer Training Data indefinitely"

**Critical: data survives project deletion:**
> "Your logged data is not deleted when you delete your project."
> "Any Customer Training Data logged from a Project prior to the selection of the Disable Option for that Project will continue to be retained by Google."

Separate deletion request form required.

### AI Model Training

**Default: NO training on your data.**
> "Google does not use any of your content for any purpose except to provide you with the Cloud Speech-to-Text API service."
> "Data from customers who have not opted in to data logging is not stored or used by Google for anything other than providing the service."

**With opt-in:**
> "Google uses this data solely to train and improve Google products and services."
> Google grants itself "the perpetual, irrevocable right to use, de-identify and copy" logged data for developing ML technology.
> "Google owns all models, improvements of GCP Services, and any associated intellectual property, that result from Google's use of the Customer Data."

**No advertising use:**
> "Google does not use customer data or any personally identifiable information contained in logged customer data to target products, services, or advertising towards customers or customers' users."

### HIPAA Compliance

**Cloud Speech-to-Text IS a HIPAA-covered service** under the Google Cloud BAA.

> Google Cloud BAA covers "Google Cloud's entire infrastructure (all regions, all zones, all network paths, all points of presence)"

Speech-to-Text is listed among HIPAA-eligible services. Requirements:
- Customer must execute a Google Cloud BAA
- Customer must configure environment properly
- **Must NOT opt into data logging if handling PHI**

### Data Deletion Rights

> "Google does not make the audio content sent to the Cloud Speech-to-Text API available to anyone else except as necessary to provide the Cloud Speech-to-Text API service."

For opted-in data: customers must submit a separate deletion request form (referenced in Section 2.e of the data logging terms).

### Third-Party Sharing

**Default:** No sharing.
> "Google does not make the audio content sent to the Cloud Speech-to-Text API available to anyone else except as necessary to provide the Cloud Speech-to-Text API service."

**With opt-in:**
> Google may share logged data "with affiliates, third party vendors and contractors of Google, who are bound by non-disclosure agreement(s)."

---

## KEY PATTERNS & BORROWABLE CLAUSES FOR ЛАВРЕНТИЙ / WiM

### Pattern 1: Separate the "no-store default" from "opt-in training"
Google's approach is the gold standard here. Default = no storage, no training. Opt-in = you get benefits but Google gets training rights. For Лаврентий/WiM, the equivalent:
- Audio sent to OpenAI Whisper API for transcription is processed and returned; we do not store raw audio
- Session transcripts stored locally on your device only
- No data sent to any third party for model training

### Pattern 2: Voice samples are NOT sensitive data (Speechify)
> "Although you can upload voice samples to our Service, those samples are not sensitive data because we do not use them for the purposes of identifying you."

This classification matters for Лаврентий because voice profiles ARE used to understand the user's speech patterns — potentially classifiable as biometric data in some jurisdictions (IL BIPA, TX CUBI, WA).

### Pattern 3: Real-time processing, no recording (Doxy.me)
> "The session is never recorded or otherwise stored. It happens in real-time."

This is directly applicable to Лаврентий's architecture where audio is streamed to the API and not persisted.

### Pattern 4: 12-month post-termination cap (Speechify Studio)
> "No purpose in this Privacy Policy will require us keeping your personal information for longer than twelve (12) months past the termination of the user's account."

Concrete, user-friendly, borrowable.

### Pattern 5: HIPAA is a separate agreement, not in the base policy
Both Otter.ai and Doxy.me handle HIPAA via separate BAA documents, not in the main privacy policy. The base policy covers consumer use; HIPAA is layered on top for qualifying users/plans.

### Pattern 6: Third-party API disclosure
Otter.ai names its cloud providers (AWS), analytics providers (Amplitude, Google), and payment processors (Stripe). Google names affiliates and NDA-bound contractors. For Лаврентий/WiM, the disclosure should name:
- OpenAI (transcription/reconstruction via Whisper API)
- Firebase/Google (authentication)
- Any analytics if added later

### Pattern 7: On-device vs. cloud distinction (Speechify)
> "User Content you save will be stored locally on that device and synced with our servers."
> "stored solely on your device...never sent to Speechify servers."

Directly maps to Лаврентий's architecture: profile data local, session history local, only audio streams to OpenAI transiently.

### What NONE of them do (gap for Лаврентий to fill):
- None of these competitors explicitly address stuttering, speech disorders, or clinical voice reconstruction
- None address the specific pattern of "audio goes to third-party API, reconstruction happens, original audio is never stored"
- None address the ethical dimension of voice data for people with speech disabilities
- Doxy.me comes closest to the clinical framing but is a video platform, not a voice reconstruction tool

### Recommended Policy Architecture:
1. **Single policy** covering both Лаврентий (Windows) and WiM (Android)
2. **Name OpenAI explicitly** as the third-party processor (like Otter names AWS)
3. **Adopt Doxy.me's "never recorded" language** for audio streams
4. **Adopt Speechify Studio's 12-month cap** for data retention post-deletion
5. **Adopt Google's "default no-training" stance** — make it crystal clear no data is used for AI training by you or OpenAI
6. **Address biometric data proactively** — voice profiles may trigger BIPA/CUBI in certain states
7. **Layer HIPAA separately** if/when clinical partnerships emerge — don't bake it into v1 consumer policy
8. **Reference OpenAI's own data usage policy** (as of March 2025, API data is not used for training by default)
