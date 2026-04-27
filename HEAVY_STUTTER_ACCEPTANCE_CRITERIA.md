# Heavy-Stutter Acceptance Criteria — Foundation-Outreach Bar

**Purpose.** Define the quantitative thresholds Lavrentiy must clear on the heavy-block test corpus (`heavy_stutter_test_scripts.json`, 18 cases) at L4 before the project is fit to pitch to a research foundation. Anchored to published baselines from FluencyBank Timestamped (Bayerl/Romana 2024) and SEP-28k (Lea 2021).

## The four metrics

The harness (`test_heavy_stutter.py`) emits four scores per case per layer. All thresholds below apply to **L4** (full reconstruction) on the **median** across the 18-case set, unless otherwise noted.

| Metric | Definition | Why it matters |
|---|---|---|
| WER (vs intended) | Levenshtein-token error rate of reconstructed output against the ground-truth intended utterance. Lower = better. | The headline number reviewers will compare against the FluencyBank Whisper baseline. |
| Intent Jaccard | Set Jaccard over content lemmas (stopwords + fillers stripped). 1.0 = perfect content overlap. Higher = better. | Cheap offline proxy for semantic preservation. Catches cases where WER looks low but the meaning shifted. |
| Coverage | Recall of intended content lemmas in the output. Higher = better. | Catches information loss. WER alone tolerates over-aggressive deletion; coverage punishes it. |
| Proper-noun preservation rate | Fraction of intended proper nouns appearing verbatim in output. Higher = better. | Names, places, days of the week, numbers — non-negotiable for clinical/legal/professional use. |

## The thresholds

### L4 median, foundation-outreach floor

- **WER ≤ 0.30.** FluencyBank Timestamped reports raw Whisper at **15.4 % WER on PWS speech** (mild = 8.9 %, moderate = 12.3 %). Heavy-block speech is harder than moderate stutter — expect raw Whisper to land 35–55 % WER on this corpus. Lavrentiy at 0.30 represents a **measurable lift over raw ASR** on the hard case. 0.20 is the stretch goal; 0.30 is the ship-it-to-foundations floor.
- **Intent Jaccard ≥ 0.70.** Below 0.70 means the reconstruction is dropping or substituting too much content to claim intent preservation in a deck.
- **Coverage ≥ 0.85.** No more than 15 % of intended content words missing on the median case. Drops below this on individual cases are acceptable only when paired with a Falcon FAIL (the system correctly bailed to raw text).
- **Proper-noun preservation ≥ 0.90 (mean across cases).** Hard floor. A reconstruction system that loses Henderson, Marriott, Tuesday, or Thursday is not fit for clinical or professional use. SEP-28k's lay-annotator block kappa of 0.25 underscores why human verification of names is impractical at scale — the model has to get this right on its own.

### Behavioral rules (per-case, not aggregate)

- **Self-correction respected.** Cases h05 (`I mean`) and h06 (`actually`) must reconstruct to the *corrected* content, never the placeholder. Hard fail if either case lands the wrong word.
- **Phantom-word collapse.** Cases h02 and h16 (Whisper-hallucinated `so so so` and `the the the the`) must NOT preserve the phantom token cluster. WER ≤ 0.20 on these two specifically.
- **No softening on consequential phrases.** Case h14 (`I do not consent`) must keep the negation. Reconstruction that produces hedged language (`I'm not sure I consent`, `I prefer not to`) is a hard fail regardless of WER.
- **Falcon discipline.** If reconstruction quality drops below the threshold on a case, Falcon should reject and the system should fall back to raw — that is the system working as designed, not a failure. Acceptance allows up to 3/18 cases to be Falcon-FAIL provided the failures correlate with the lowest-quality reconstructions.

### Lift-over-baseline bar (the actual pitch)

- **L4 vs L1.** L4 must beat L1 (disfluency-strip only, no API call) by ≥ 0.25 WER absolute on the median heavy-block case. Without that gap, the LLM layer is not earning its cost.
- **L4 vs raw input.** Across the 18 cases, L4 must reduce WER by ≥ 50 % compared with running the raw disfluent input directly against the intended ground truth.

## What this corpus does NOT prove

This is a text-only synthetic corpus. Clearing these thresholds does **not** prove Lavrentiy works on real audio from heavy-block speakers — that requires a separate audio harness against SEP-28k block clips and/or FluencyBank Voices-AWS recordings (see corpus research memo §6). The text harness is necessary but not sufficient. Foundation outreach should pair this report with at least 5–10 real-audio reconstructions from the SEP-28k block subset.

## Re-run policy

Re-run the full L1-L4 sweep after any change to: domain packs, L1 packs, the reconstruction prompt stack, the Falcon validator, the rejection store, or the OpenAI model version. Diff WER deltas case-by-case. Any individual case regressing >0.10 WER absolute is a release blocker.
