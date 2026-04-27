# Heavy-Stutter Corpus Landscape — Research Memo

**Scope.** Public datasets usable for evaluating Lavrentiy's reconstruction quality on **hard speech blocks** (long silent freezes, frozen onsets, gasping pauses) — distinct from "severe but audible" stutter (overt sound repetitions, prolongations).

**Bottom line up front.** The field has solid coverage of audible disfluencies (repetitions, prolongations, fillers) and weak coverage of silent blocks. **No publicly licensed corpus treats blocks as a first-class, tightly-annotated unit.** SEP-28k labels blocks but with 0.25 Fleiss kappa — borderline noise. FluencyBank Timestamped, the cleanest 2024 benchmark, *explicitly excludes blocks*. KSoF (German, therapy) is the best block-labeled set but is access-restricted and not English. UCLASS predates the block taxonomy debate. For Lavrentiy's foundation pitch, the realistic move is: synthesize a heavy-block test corpus from text (this memo's companion JSON), validate qualitatively against SEP-28k block clips, and use FluencyBank Timestamped's WER baselines (15.4 % Whisper on PWS speech) as the comparison anchor.

---

## 1. SEP-28k — Apple/CMU, 2021

- **What it is.** ~28,000 three-second clips from 8 podcast shows, 385 episodes; speakers are PWS interviewing PWS. ~4,000 additional clips drawn from FluencyBank.
- **Block coverage.** Yes — block is one of five labels (block, prolongation, sound repetition, word repetition, interjection). Blocks ≈ 12 % of clips → ~3,381 block-labeled segments.
- **Annotation quality.** Inter-annotator Fleiss kappa is alarming for the targets we care about most: **blocks 0.25, prolongations 0.11.** Sound repetitions 0.40. Word repetitions 0.62, interjections 0.57. Annotators were lay (not clinicians). Authors note: *"Blocks can be difficult to assess from audio alone; clinicians often rely on physical signs of grasping for air."* That admission is the corpus's biggest limitation for our use case.
- **License.** CC BY-NC 4.0.
- **Distribution.** Apple releases labels + episode CSVs only. Audio must be downloaded from podcast hosts via provided URLs. Some shows have churned off the open web; expect partial recovery.
- **arXiv.** 2102.12394. GitHub: github.com/apple/ml-stuttering-events-dataset.
- **Use for Lavrentiy.** Sample block-labeled clips qualitatively, transcribe with Whisper, and use those transcripts as ground for additional heavy-block test scripts. Do **not** rely on its block label as a reconstruction-quality oracle — the kappa is too low.

## 2. FluencyBank Timestamped — Penn / Bayerl, 2024

- **What it is.** Updated transcripts + word-level timings + disfluency labels for the FluencyBank Voices-AWS subset. **5.3 hours of audio, 37 adults who stutter.** Published JSLHR Nov 2024 (DOI 10.1044/2024_JSLHR-24-00070).
- **Block coverage.** **None.** Labels are filled pauses, repetitions, revisions, partial words. Authors explicitly call out blocks and prolongations as missing and invite future work.
- **Why it still matters.** It's the only 2024-vintage, token-aligned, English, PWS-focused corpus with published Whisper benchmarks:
  - **Whisper intended-speech WER on PWS = 15.4 %** (vs 15.2 % on Switchboard typical speech). Mild PWS = 8.9 %, moderate = 12.3 %.
  - BERT text-based disfluency F1: 0.73 weighted (vs 0.85 on Switchboard).
  - Whisper audio-based disfluency F1: 0.46 weighted (vs 0.62 on Switchboard).
  These numbers anchor Lavrentiy's "we beat raw Whisper on PWS speech" claim.
- **License/access.** TalkBank consortium membership required. Free for research. Teaching subset is public.
- **URL.** talkbank.org/fluency, pubs.asha.org/doi/10.1044/2024_JSLHR-24-00070.
- **Use for Lavrentiy.** Apply Whisper → Lavrentiy on the Voices-AWS audio, compute WER vs the timestamped intended transcripts, and report delta vs the 15.4 % Whisper baseline. This is the cleanest comparable number Lavrentiy can publish.

## 3. KSoF — Kassel State of Fluency, TH Nürnberg / 2022

- **What it is.** 5,597 segments from therapy sessions at Institut der Kasseler Stottertherapie. Six labels: block, prolongation, sound repetition, word repetition, interjection, **plus speech modification** (therapy-specific — speakers using fluency-shaping techniques).
- **Block coverage.** Yes, first-class. Best block-labeled corpus in the field by intent.
- **Language.** German.
- **License/access.** Restricted; available "upon request" via TH Nürnberg / Zenodo (10.5281/zenodo.6801844). LREC 2022.
- **Use for Lavrentiy.** Limited — German doesn't help English-speaking foundation pitch. Cite as evidence the field acknowledges blocks as a discrete, labelable category. Possibly relevant later if Lavrentiy pursues multilingual.

## 4. UCLASS — UCL, Howell et al., 2009

- **What it is.** Two releases of audio from school-age PWS (mostly 8–10 yr) referred to UCL clinics. Release 1 = monologs only. Release 2 = monologs, readings, conversations. CHAT, PRAAT TextGrid, SFS transcripts available.
- **Block coverage.** Predates the SEP-28k label taxonomy. Transcripts use CHAT-style disfluency markers; blocks not consistently coded as a separate category. Audible disfluencies dominate.
- **License.** Free for research/teaching, attribution required (Wellcome Trust funded).
- **URL.** uclass.psychol.ucl.ac.uk. PMC 2939977, PubMed 19339703.
- **Use for Lavrentiy.** Adult-pitch relevance is low (children speakers). Still useful for Whisper transcription stress-testing on disfluent reading passages.

## 5. LibriStutter — OSU SLATE Lab

- **What it is.** **Synthetic** stutter overlay on LibriSpeech audio. 20 hours. Sound repetitions, word repetitions, phrase repetitions, prolongations, interjections.
- **Block coverage.** No — synthesis is sample-based and cannot generate authentic silent blocks (a block is the *absence* of sound paired with physiological tension; can't be cut-and-pasted).
- **Use for Lavrentiy.** Skip. Synthetic = wrong distribution for the case George cares about.

---

## 6. Recommended corpora for Lavrentiy's foundation-outreach test (priority order)

1. **SEP-28k block subset** — pull the ~3,381 block-flagged clips, transcribe with Whisper, hand-curate the 30–50 cleanest hard-block examples, run through Lavrentiy. License is CC BY-NC, fine for research presentation.
2. **FluencyBank Timestamped Voices-AWS** — full corpus, compute Whisper-only WER vs Whisper→Lavrentiy WER. Anchor against the published 15.4 % baseline. Membership barrier is low for legitimate research.
3. **Synthetic heavy-block test scripts** (this delivery's companion `heavy_stutter_test_scripts.json`) — bridges the gap until authentic block audio is curated. Twenty scripts spanning silent blocks, abandonment, hallucinated phantom words, covert revision.

## 7. What is genuinely missing in the field

- **No English, clinically-annotated, public corpus with first-class block labels** that has a usable Fleiss kappa. SEP-28k has the labels but lay annotators and 0.25 kappa. KSoF has the methodology but is German and gated. FluencyBank Timestamped has the rigor but skips blocks entirely.
- **Multi-modal (audio + video)** is what real block annotation needs (the gasp / facial tension cue), and no public set provides it.
- This gap is itself a foundation-pitch angle: Lavrentiy is being built without a benchmark, and producing one is part of the contribution.

---

## Citations

- Lea et al. (2021). *SEP-28k: A Dataset for Stuttering Event Detection From Podcasts With People Who Stutter.* arXiv:2102.12394. ICASSP 2021.
- Bayerl et al. (2022). *KSoF: The Kassel State of Fluency Dataset.* LREC 2022. arXiv:2203.05383.
- Howell et al. (2009). *The University College London Archive of Stuttered Speech.* J. Speech Lang. Hear. Res.
- Romana et al. (2024). *FluencyBank Timestamped.* JSLHR. DOI 10.1044/2024_JSLHR-24-00070. PMC12379651.
- Kourkounakis et al. (2020). *FluentNet / LibriStutter.* arXiv:2009.11394.
- Wagner et al. (2024). *Large Language Models for Dysfluency Detection in Stuttered Speech.* Interspeech 2024.
