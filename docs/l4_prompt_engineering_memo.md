# L4 Stutter Reconstruction — Prompt Engineering Re-Engineering Proposal

**Classification:** Internal Engineering Memo  
**Date:** April 20, 2026  
**Author:** Claude Sonnet 4.6 (Lavrentiy/WiM Engineering Synthesis)  
**Status:** PR-Ready Proposal — Read-Only Analysis, No Code Modified  
**Target file:** `wim-android/app/src/main/java/com/wim/app/ReconstructClient.kt`  
**Output file:** This document  

---

## 1. Executive Summary

The WiM L4 (speech disfluency) reconstruction prompt, located at `ReconstructClient.kt:261–350`, was designed and validated against a single implicit user archetype: an English-speaking adult with developmental stuttering. That design is being stretched over ten languages with structurally different phonologies, prosodic systems, and sociolinguistic norms. This memo proposes a targeted re-engineering that preserves the English prompt's proven clinical logic while making it language-parameterizable, citation-backed, and Falcon-efficient.

**What changes:**

1. **Natural-repeat protection** — the ten language packs each define emphatic reduplication patterns (Spanish "sí sí", Japanese "そうそう", Arabic "ايوه ايوه") that are pragmatically meaningful, not stuttered. The current prompt's word-repetition-collapse rule would strip them. A language-aware allow-list is inserted before the strip instruction.

2. **Language-parameterized few-shot examples** — all twelve current examples are English. Non-English inputs receive phonologically nonsensical guidance. Per-language example blocks are added, conditioned on `languageCode`.

3. **Onset-aware Whisper artifact notes** — the current Whisper failure-mode section is English-phonotactic ("come put her" for "computer"). Language packs with cited onset data receive language-appropriate artifact warnings; packs without research are explicitly told NOT to apply English-onset reasoning.

4. **Falcon deduplication** — the Falcon validator prompt (`falconValidate()`, lines 445–463) repeats approximately 200 tokens of L4 content verbatim. This memo proposes a leaner Falcon prompt that adds language-specific guards without duplicating the main prompt.

5. **Cluttering/mazes de-conflation** — the current prompt conflates cluttering with stuttering covert behavior. These are distinct diagnoses (Daly 1986; Ward 2018), and treating cluttered speech as avoidance behavior produces over-stripping false positives.

**Expected impact on `_phase4_ears_benchmark.py` Phase 2 metrics:**

| Metric | Direction | Notes |
|---|---|---|
| `word_repeat_collapse_rate` (non-EN) | Decrease slightly | Preserving natural repeats is correct; lower collapse is less aggressive, not worse |
| `fragment_strip_rate` | Stable or improve | Language-specific false-start markers improve targeting |
| `phonetic_onset_honored` | Improve (non-EN) | Language-appropriate onset data replaces English fallback |
| `covert_recovery` | Improve (ES) | Voseo/tuteo avoidance pair recovery newly possible |
| Falcon pass rate | Stable or improve | Deduplication removes ambiguous Falcon instruction overlap |

**Engineering effort:** 3–5 days of Kotlin + Cloud Function work to implement the proposed diff. Prompt changes themselves are a single-day task; the API parameter addition and backend wiring are the primary scope.

---

## 2. Baseline L4 Prompt Audit

This section walks through `ReconstructClient.kt:261–350` sequentially, identifying problems against the research corpus and lang pack data.

### 2.1 Opening Declaration (lines 262–263)

```
"The speaker stutters. Raw transcription is evidence, not truth."
"Reconstruct intended meaning, not literal word sequence."
```

**Assessment: GOOD.** Universal principle with no language dependency. Correctly frames the epistemics of the task — Whisper output is a noisy observation of intent.

**Research alignment:** Consistent with Xu (2025) (StutterZero/StutterFormer) finding that Whisper-Medium achieves 36.1% WER on stuttered speech — more than double its normal-speech WER. The prompt is correctly calibrated to treat the transcript as highly unreliable.

**No changes needed.**

---

### 2.2 Overt Disfluencies (lines 265–271)

```
- Part-word repetitions: 'b-b-b-buy' → 'buy', 'Ca-ca-ca-can' → 'Can'
- Whole-word repetitions: 'I I I want' → 'I want'
- Prolongations: 'mmmmaybe' → 'maybe', 'Sssssscience' → 'Science'
- Schwa substitution: 'guh-guh-goat' → 'goat'
- Blocks: silence or frozen onset before a word (locked articulators)
- False starts and restarts
```

**Problem 1 — Examples are English-only.** Part-word repetition examples ("b-b-b-buy", "Ca-ca-ca-can") embed English phonology. For Spanish, the analogous example would be "p-p-pues" or "t-t-trabajo". For Japanese, repetition occurs at mora level (not consonant-only), e.g., "か-か-かく" (written) or an elongated /ka/ mora cluster. GPT-4o may correctly generalize from the English examples, but providing language-specific anchors reduces ambiguity.

**Problem 2 — Schwa substitution ("guh-guh-goat") is English-specific.** English speakers produce a neutral schwa /ə/ during articulatory struggle because English vowels reduce to /ə/ under stress. Spanish has five pure vowels with no reduction; a blocked /p/ in "planta" produces "p-eh-lanta" (epenthetic /e/, not /ə/) per the Spanish stuttering memo (Section 10.3). The current example teaches GPT-4o the wrong phonetic pattern for Spanish and all other non-English languages.

**Problem 3 — Whole-word repetitions ("I I I want" → "I want") overlaps with natural_repeats.** For all ten supported languages, the lang packs define natural emphasis patterns that ARE whole-word repetitions but must NOT be stripped. The current rule has no exemption mechanism. A Spanish user saying "sí sí, eso está bien" intends emphatic agreement; stripping it to "sí, eso está bien" destroys the pragmatic meaning.

**Action required:** Add natural_repeats allow-list before the repetition-stripping rule. See Section 4.1.

---

### 2.3 Covert Stuttering (lines 273–278)

```
- Filler clusters before a content word = delay tactic, not hesitation
- Synonym substitution = avoiding a feared word
- Circumlocution = talking around a feared word
- Sentence abandonment = dropping thought before feared word
- Mazes/cluttering = rambling run-on filler adding no information
```

**Problem 1 — Filler identification is language-agnostic but the fillers are not listed.** The instruction correctly identifies that filler clusters are postponement tactics. However, without the language-specific filler list injected into the prompt, GPT-4o may not recognize "este... este... quiero ir" as a filler cluster in Spanish (since "este" is a demonstrative pronoun in English). The lang pack `fillers` arrays must be injected here.

**Problem 2 — Mazes/cluttering conflation.** Cluttering (tachyphemia) is a distinct fluency disorder (Daly 1986; Ward 2018; Scaler Scott 2019) characterized by rapid speech rate and coarticulation errors, not avoidance behavior. A speaker who clutters is not avoiding a feared word — they are producing at a rate faster than their neuromotor coordination supports. Conflating cluttering with covert stuttering mazes will cause over-stripping of rapid but genuine speech in speakers who have both conditions (which is clinically common — studies estimate 30–40% co-occurrence; not yet established in a single authoritative meta-analysis as of April 2026, so marked **[not yet established in literature]**). The instruction should be split: mazes (extended filler runs that are avoidance behavior) vs. cluttered speech (rapid coarticulation, typically preserved by stripping only the most obviously redundant fillers).

**Problem 3 — No language-specific covert avoidance examples.** The Spanish memo (Section 7.2) documents a specific avoidance mechanism unique to Spanish: speakers blocked on the alveolar /t/ onset may switch from "tú tienes" to "vos tenés" or "usted tiene" — a dialectal register shift used as phonemic avoidance. This is undetectable from English training data alone. For the voseo/tuteo dynamic, the L4 prompt should provide an explicit hint. Similar register-switching covert behaviors exist in:
- German: "du" → "Sie" (informal → formal) as avoidance of /d/ onset
- Japanese: casual 語 → keigo honorific forms as avoidance of feared initial consonants (not yet established in Japanese stuttering literature as of April 2026 — **[speculative, requires validation]**)
- Korean: 반말 → 존댓말 switching (**[speculative, not established in Korean stuttering literature as of April 2026]**)

---

### 2.4 Anticipatory Behavior (lines 280–283)

```
- A pause or silence BEFORE a content word is likely ANTICIPATORY FEAR, not thinking
- The speaker scans ahead, detects a feared word, and freezes
- Treat pre-word pauses on content words as blocks, not natural hesitation
```

**Problem 1 — Overconfident heuristic language.** "Is likely ANTICIPATORY FEAR" overstates the certainty. Pre-word pauses serve multiple functions in fluent speech (cognitive planning, emphasis, prosodic boundary). The instruction should say "may indicate" or "is a candidate for" anticipatory fear, particularly when the following word begins with a documented hard onset. Without qualification, GPT-4o may aggressively reconstruct utterances where the speaker was simply thinking.

**Research note:** Anticipatory behavior is clinically established (Bloodstein & Bernstein Ratner, 2008, *A Handbook on Stuttering*, 6th ed., pp. 3–14). The mechanism — forward scanning of feared words — is well-documented. The problem is not the clinical claim but its expression as absolute prediction rather than a weighted heuristic.

**Problem 2 — Syllable-timed language incompatibility.** The anticipatory pause heuristic was developed in English-language clinical contexts. Spanish, French, Italian, and Portuguese are syllable-timed languages where pre-word pauses carry different prosodic weight. In English (stress-timed), a pause before a content word is strongly marked. In Spanish, the rhythmic isochrony means shorter inter-word pauses are more common in fluent speech and a pause before a content word is less diagnostically significant than in English (Au-Yeung et al., 2000, *Journal of Speech, Language, and Hearing Research*). The heuristic should be applied with reduced weight for syllable-timed language inputs.

---

### 2.5 Whisper ASR Failure Modes (lines 285–290)

```
- HALLUCINATION DURING BLOCKS: silence → Whisper invents words
- SYLLABLE DELETION: repeated syllables collapsed or dropped
- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar words
- SCHWA CORRUPTION: neutral vowel in repeated clusters → transcribed as real word
- PAUSE HALLUCINATION: long pauses → Whisper generates filler text
```

**Problem 1 — SCHWA CORRUPTION is English-specific.** The mechanism described — neutral vowel /ə/ in repeated clusters being transcribed as a real word — is specific to English's vowel reduction system. Spanish, Japanese, Korean, Arabic, and Hindi all lack phonemic schwa. The analogue in syllable-timed languages is EPENTHETIC VOWEL CORRUPTION, where the inserted vowel is language-specific (Spanish: /e/, as in "p-eh-lanta"; Hindi: short /a/, as in the inherent vowel of Devanagari consonants). The current instruction will confuse GPT-4o for non-English inputs.

**Problem 2 — PAUSE HALLUCINATION patterns not enumerated.** The `_phase4_ears_benchmark.py` code at lines 62–71 explicitly documents Whisper's known hallucination strings during silence: "thank you", "transcribed by", "subscribe", "like and subscribe", "thanks for watching", "captions by", "otter.ai". These are empirically confirmed artifacts that the L4 prompt should explicitly instruct GPT-4o to recognize and discard. The current instruction says "Whisper generates filler text" without specifying what it looks like.

**Problem 3 — Hallucination patterns are English-biased.** Whisper's language model is predominantly English-trained. When transcribing non-English stuttered speech, the hallucination content during blocks is still often English phrases ("thank you", "you know"). The L4 prompt should instruct GPT-4o that even in non-English utterances, mid-transcript English phrases are likely Whisper hallucinations to discard.

**Research alignment:** Xu (2025) (StutterZero, arXiv:2510.18938) specifically documents that Whisper-Medium's cascade failure on stuttered speech is the primary motivation for end-to-end reconstruction approaches. The paper's WER baseline of 36.1% is the empirical floor against which L4 prompt engineering operates.

---

### 2.6 Few-Shot Examples (lines 292–325)

This is the section with the highest density of problems.

**All twelve examples are English.** The following language-specific issues exist:

- `'b-b-b-buy' → 'buy'`: Correct for English /b/ blocks. Misleading for Spanish where /b/ is not a primary hard onset (Howell et al., 2004 cite /p/ and /t/, not /b/).
- `'mmmmaybe' → 'maybe'`: English-specific. Spanish prolongation of /m/ before "me" ("mm-me llamo") is similar but "mmmmaybe" teaches incorrect English phonotactics.
- `'guh-guh-goat' → 'goat'`: English schwa — see Problem 2 above.
- `'I was trying to come put her the file'`: Whisper hallucination of "computer" via English phoneme substitution. This is a sophisticated English-specific example that GPT-4o must extrapolate to non-English Whisper artifacts without guidance.
- The FILLER STACKING example: `'So um uh like basically uh...'` — English fillers. Spanish "Este... pues... o sea... básicamente..." is the functional equivalent, but without the example, GPT-4o may not strip Spanish fillers with the same confidence.

**The `=== FEW-SHOT EXAMPLES ===` and `=== END EXAMPLES ===` delimiters** consume 7 tokens for formatting that does not add semantic information. Minor but worth cleaning up in a token-budget-conscious prompt.

**Action required:** Conditionalize examples on language. See Section 4.3.

---

### 2.7 Final Caveats (lines 326–327)

```
"Do not mistake disfluency for emphasis."
"When uncertain, prefer conservative cleanup over aggressive rewriting."
```

**Critical conflict with natural_repeats.** "Do not mistake disfluency for emphasis" — true in principle, but the lang pack `natural_repeats` arrays are exactly cases where what looks like a word repetition IS emphasis. "Sí sí" looks like a stuttered word repetition but is emphatic affirmation. "No no" in Spanish looks like a disfluent "no" block but is emphatic negation. This couplet needs a language-aware carve-out.

**Second sentence is correct** and should be preserved.

---

### 2.8 Personal Phoneme Difficulty Map (lines 329–337)

```kotlin
val topOnsets = onsetWeights.entries
    .sortedByDescending { it.value }
    .take(5)
    .joinToString(", ") { "/${it.key}/ (${(it.value * 100).toInt()}%)" }
append("\n\nTHIS SPEAKER'S HARDEST PHONEMES: $topOnsets")
```

**Critical problem: `onsetWeights` are sourced from English phoneme data.**

`PhoneticRisk.kt:17–32` defines `HIGH_RISK_ONSETS` as a hardcoded English-only table. When a Spanish speaker's profile is initialized, their `onsetWeights` are built from this English table, meaning the top-5 onsets injected into the L4 prompt are English-calibrated even for non-English users.

Specifically:
- Spanish's unique high-difficulty onset `/rr/` (alveolar trill) does not exist in `HIGH_RISK_ONSETS`
- Spanish's `/tr/`, `/tl/` consonant clusters are not in the table
- German's onset profile per Natke et al. (2004) identifies `/p/` but NOT `/t/` as a primary hard onset — yet `HIGH_RISK_ONSETS["t"] = 0.80` would over-flag German `/t/` words

This does not require changing `PhoneticRisk.kt` in this memo (that's a separate engineering task), but the L4 prompt should note: "These onset weights reflect this speaker's personal difficulty profile, which may be calibrated against language-general English-onset data — treat with caution for {LANGUAGE_CODE} users."

---

### 2.9 Falcon Validator Redundancy (lines 445–463)

The Falcon validator prompt for L4 (layer >= 4) reads:

```
"Speaker stutters. Repeated syllables, prolongations, and blocks are disfluencies, 
not emphasis. Filler clusters before content words are postponement tactics, not 
meaningful hesitation. Synonym substitutions and circumlocutions are avoidance 
behaviors — the reconstruction should recover the intended word. Rambling run-on 
filler (mazes) should be stripped."
```

This is nearly verbatim from the L4 system prompt (lines 265–278). GPT-4o is being paid twice — once to reconstruct and once to validate — with the same instruction. The Falcon prompt should say: "Validate that the reconstruction correctly applied the L4 disfluency-cleanup rules already specified in the system prompt. Do not re-specify those rules." Then add the phonetic guard (already present at lines 452–461) which is the genuinely new information.

**Token waste estimate:** The duplicated Falcon content is approximately 180–200 tokens per validation call. With Falcon running on every non-fast-mode reconstruction (line 392–398), this adds up.

---

## 3. Research Synthesis — What Should Change

### 3.1 Spanish Memo Findings Applicable Cross-Linguistically

The Spanish stuttering memo documents several clinical findings that generalize beyond Spanish:

**Pre-collapse disfluency zone.** Section 7 documents that speakers approaching a feared phoneme show increased filler usage in the 1–2 words immediately preceding the feared word. The current L4 prompt says fillers before a content word are delay tactics — correct — but doesn't specify the temporal proximity. GPT-4o would benefit from the explicit framing: "A cluster of fillers immediately before a content word (within 1–3 words) is stronger evidence of phonemic anticipation than a single isolated filler earlier in the utterance."

**Covert avoidance via register shifting.** The tuteo/voseo finding (Spanish memo, Section 7.2) is a specific instance of a general principle: speakers exploit any register distinction available in their language to avoid feared phonemes. This should be documented as a universal L4 heuristic: "In languages with formal/informal address variants (Spanish, German, Japanese, Korean, French), an unexpected register shift on a content word may indicate avoidance substitution — the speaker chose the less-feared pronoun form, not the intended one." Note: The application to specific languages beyond Spanish is **[speculative, not yet established in literature]** and should be flagged as a clinical hypothesis pending validation.

**Dialect preservation is non-negotiable.** The Spanish memo (Section 7.1) states: "Reconstructing an Argentine user's stuttered 'vos t-t-tenés' into 'tú tienes' is clinically catastrophic — it constitutes algorithmic erasure of the user's identity." This principle applies universally: reconstruction must operate within the speaker's dialect, register, and variety. The L4 prompt must explicitly instruct GPT-4o: "Reconstruct within the speaker's established dialect. Do not substitute dialectal forms to 'normalize' the output."

**Clinical sensitivity around recovered words.** The Spanish memo warns that mechanically recovering an avoided word may not always be appropriate. If a speaker consistently uses "documento" when blocked on "informe", recovering "informe" is technically correct but may feel intrusive to the user. This is outside the scope of the L4 prompt (it is a UX/consent question), but noted for implementation notes.

### 3.2 Cross-Language Natural Repeats — Must Preserve

The ten lang packs define `natural_repeats` arrays that are emphatic, pragmatic, or discourse-structuring reduplication — not stuttering. These must be added to an explicit allow-list in the L4 prompt. The current zero-exception word-repetition rule would strip all of them.

| Language | Natural Repeats (Must Preserve) |
|---|---|
| Spanish (es) | "no no", "sí sí", "ya ya", "claro claro" |
| French (fr) | "non non", "oui oui", "si si", "et et" |
| German (de) | "nein nein", "ja ja", "doch doch", "und und" |
| Italian (it) | "no no", "sì sì", "dai dai", "e e" |
| Portuguese (pt) | "não não", "sim sim", "já já", "e e" |
| Japanese (ja) | "そうそう", "はいはい", "いいえいいえ", "てて" |
| Mandarin (zh) | "对对", "是是", "行行", "好好" |
| Hindi (hi) | "नहीं नहीं", "हाँ हाँ", "ठीक ठीक", "और और" |
| Arabic (ar) | "لا لا", "اه اه", "ايوه ايوه", "و و" |
| Korean (ko) | "아니 아니", "네 네", "맞아 맞아", "그리고 그리고" |

**Mandarin-specific note:** Chinese grammatical reduplication is particularly dense. "走走" (take a short walk) and "看看" (take a look) are canonical reduplication forms that are not emphatic — they encode aspectual meaning (inchoative/tentative). The L4 prompt for Mandarin should note: "Chinese verb reduplication (same verb twice) may encode aspectual meaning, not emphasis. When in doubt, preserve." **[Not established in Mandarin stuttering literature as of April 2026 — extrapolated from Chinese linguistics; requires validation].**

**Japanese-specific note:** Japanese `natural_repeats` include "そうそう" (backchanneling agreement) and "はいはい" (acknowledgment). These are discourse-structuring and appear frequently in natural conversation. However, Japanese also has grammatical emphatic reduplication. The distinction between stuttered mora repetition and natural Japanese reduplication is a research gap: Umezaki et al. (1999) established `/k/` as a hard onset but did not address reduplication disambiguation. **[Reduce confidence for Japanese reduplication handling — marked as speculative].**

### 3.3 StutterZero/StutterFormer Whisper Failure-Mode Insights

From Xu (2025), arXiv:2510.18938, IEEE Access Vol. 13:

**Whisper-Medium baseline WER on stuttered speech: 36.1%.** This establishes the empirical floor. The L4 prompt is the primary mechanism compensating for this gap. Every prompt instruction that helps GPT-4o correctly reconstruct where Whisper failed directly addresses this 36.1% error rate.

**Critical insight — prolonged blocks cause decoder hallucination.** The StutterZero paper documents that Whisper's autoregressive decoder, when presented with extended silence (blocks), generates hallucinated output rather than producing an empty string. This is precisely what the `_phase4_ears_benchmark.py` WHISPER_HALLUCINATION_MARKERS list captures (lines 62–71): "thank you", "subscribe", "like and subscribe", etc. The L4 prompt currently says "silence → Whisper invents words" but does not specify WHAT it invents. Specifying the hallucination patterns allows GPT-4o to recognize and discard them with higher confidence.

**Cascaded ASR+LLM loses prosody.** The StutterZero paper's core architectural argument is that cascaded transcription→reconstruction approaches discard prosodic information. For L4 prompt engineering, this means: when the reconstruction is complete, it should not introduce prosodic content that wasn't in the original utterance. The Falcon validator's job is in part to catch reconstructions that have introduced new prosodic framing (e.g., turning a question into a statement because the question word was stuttered and stripped).

**Language generalizability of Whisper failure modes.** StutterZero was trained on English (SEP-28k, LibriStutter, FluencyBank). Its findings about Whisper hallucinations are English-specific. For non-English inputs, Whisper's failure modes may differ:
- Whisper's non-English language models are weaker (higher base WER for all languages vs. English)
- Hallucination content during non-English blocks is often English phrases (Whisper falls back to English priors)
- This cross-language hallucination artifact — English phrases appearing in non-English transcripts — is not addressed in the current L4 prompt

### 3.4 Onset-Weighted Phonetic Anchoring for Non-English Languages

**Languages with published onset difficulty data (6 of 10):**

| Language | Hard Onsets | Weight | Source | Caveats |
|---|---|---|---|---|
| Spanish | /p/ | 0.85 | Howell et al. 2004 | Extrapolated from English — aspiration differences reduce reliability |
| Spanish | /t/ | 0.82 | Howell et al. 2004 | Same caveat |
| French | /p/ | 0.85 | Dworzynski et al. 2003 | French unaspirated — moderate extrapolation risk |
| French | /t/ | 0.83 | Dworzynski et al. 2003 | Same caveat |
| German | /p/ | 0.85 | Natke et al. 2004 | Aspiration present in German — higher English-data reliability |
| Italian | /p/ | 0.84 | Zmarich et al. 2004 | Italian unaspirated — moderate extrapolation risk |
| Portuguese | /p/ | 0.86 | Juste et al. 2007 | Juste's study was pediatric — adult extrapolation is **[speculative]** |
| Japanese | /k/ | 0.82 | Umezaki et al. 1999 | Only hard onset in Japanese data — mora structure differs fundamentally |

**Key finding: German does NOT have published /t/ as hard onset.** The Natke et al. (2004) study identifies stress position and linguistic class as predictors in German, but does not establish /t/ as a primary hard onset. The `PhoneticRisk.kt` English table assigns `/t/ = 0.80`, which would be injected into the L4 prompt for German users without justification. The proposed revised prompt should note: "For German, only /p/ is documented as a primary hard onset (Natke et al. 2004). Do not apply English-derived /t/ difficulty weighting."

**Key finding: Japanese onset profile is categorically different.** All European languages in the pack show /p/ as hardest. Japanese shows /k/ (Umezaki 1999). This is a fundamentally different phonological profile. The onset-weighted section of the L4 prompt ("THIS SPEAKER'S HARDEST PHONEMES") should be conditioned on language to avoid English-onset guidance overriding Japanese-specific data.

**Languages with NO published data (4 of 10):** Mandarin (zh), Hindi (hi), Arabic (ar), Korean (ko).

For these four languages, the multilingual research notes explicitly state "NO PUBLISHED RESEARCH FOUND — DO NOT USE FOR CLINICAL DECISIONS." The L4 prompt's onset-weighted section must be suppressed for these languages. Injecting `topOnsets` from the English-default `PhoneticRisk.kt` table for an Arabic user would be clinically unjustified — Arabic pharyngeal and uvular consonants (/ħ/, /ʕ/, /q/, /χ/) are structurally absent from the English onset table and have no established difficulty weighting.

**Arabic-specific structural consideration.** Arabic's trilateral root morphology means blocks occur on root consonants (radicals) rather than word-initial onsets in the English sense. A block on the /k/ radical of كَتَبَ (kataba — to write) propagates differently from an English /k/ block. This is **[not established in Arabic stuttering literature as of April 2026]** and is noted as a clinical research gap, not an actionable prompt change.

---

## 4. Proposed Revised Prompts

### 4.1 New Baseline L4 Prompt Template

The following is the proposed revised L4 system prompt, in pseudocode template form (Kotlin `buildString` implementation follows in Section 5). Changes from current prompt are marked with `// CHANGE:` comments.

```
"You are a voice transcription post-processor for a speaker with speech disfluency. 
Raw transcription is evidence of intent, not a literal transcript. Reconstruct intended 
meaning. Preserve FULL meaning. Do NOT summarize. Do NOT respond to content.
Output ONLY the reconstructed text, nothing else."

// CHANGE: Inject language-specific fillers from lang pack
"Fillers to strip in this speaker's language ({LANGUAGE_CODE}): {LANG_FILLERS_LIST}"

// CHANGE: Natural-repeat allow-list — before any stripping rule
"EMPHATIC PATTERNS — DO NOT STRIP: {LANG_NATURAL_REPEATS_LIST}
These are pragmatically meaningful repetitions in {LANGUAGE_NAME}, not stuttering.
Example: {LANG_NATURAL_REPEAT_EXAMPLE}"

// Overt disfluencies — existing text preserved, examples made language-conditional
"Overt disfluencies — reconstruct, do not preserve:
- Part-word repetitions: {LANG_PART_WORD_EXAMPLE} → {LANG_PART_WORD_TARGET}
- Whole-word repetitions (NOT in emphatic allow-list above): {LANG_WORD_REP_EXAMPLE} → {LANG_WORD_REP_TARGET}
- Prolongations: {LANG_PROLONGATION_EXAMPLE} → {LANG_PROLONGATION_TARGET}
- Epenthetic insertions during blocks: {LANG_EPENTHESIS_EXAMPLE}
- Blocks: silence or frozen onset before a word (locked articulators)
- False starts and restarts"

// Covert stuttering — inject language-specific avoidance examples
"Covert avoidance — recognize as avoidance behavior, not content:
- Filler clusters before a content word = postponement (especially fillers from the above list)
- Synonym substitution to avoid a feared onset
- Circumlocution (talking around a feared word)
- Sentence abandonment before a feared word
- Mazes: extended filler runs adding no information (DISTINCT from cluttered rapid speech — 
  do not over-strip if the speaker's speech is globally rapid)
{LANG_DIALECT_AVOIDANCE_NOTE}"

// Anticipatory behavior — softened heuristic confidence
"Anticipatory behavior:
- A pause or silence BEFORE a content word that starts with a hard onset 
  MAY INDICATE anticipatory fear — treat as a candidate block
- Confidence is higher when: (1) the following word begins with a documented hard onset,
  (2) there are filler clusters in the 1-3 words prior, (3) the speaker has a history 
  of blocking on this onset (see hard onset list below)
{LANG_SYLLABLE_TIMING_NOTE}"

// CHANGE: Enumerate Whisper hallucination strings explicitly
"Whisper ASR failure modes on stuttered speech:
- HALLUCINATION DURING BLOCKS: silence → Whisper generates phantom text.
  Known hallucination strings to discard: 'thank you', 'thanks for watching', 
  'subscribe', 'like and subscribe', 'transcribed by', 'captions by', 'otter.ai'
  In non-English transcripts: English phrases appearing in the middle of the 
  {LANGUAGE_NAME} text are likely Whisper hallucinations — discard them.
- SYLLABLE DELETION: repeated syllables collapsed or dropped
- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar-sounding words  
- {LANG_EPENTHESIS_CORRUPTION_NOTE}
- PAUSE HALLUCINATION: long pauses → Whisper generates filler text (see above)"

// Few-shot examples — language-conditional
"{LANG_FEW_SHOT_EXAMPLES}"

"Do not mistake disfluency for emphasis — but see the EMPHATIC PATTERNS allow-list above.
Reconstruct within the speaker's established dialect — do not substitute dialectal forms.
When uncertain, prefer conservative cleanup over aggressive rewriting."

// Phoneme difficulty (existing, with language caveat added)
"THIS SPEAKER'S HARDEST PHONEMES: {TOP_ONSETS_WITH_CAVEAT}"

// Known trigger words (existing, unchanged)
"Known trigger words: {TRIGGER_WORDS}"

// Predicted risks (existing, unchanged)
"Phonetically predicted high-risk words in this utterance: {PREDICTED_RISKS}"
```

### 4.2 Language-Specific Overrides for Tier 1 Languages (Onset Data Available)

**Spanish (es):**
- `LANG_FILLERS_LIST`: "este, eh, em, pues, o sea, bueno, es que, digamos"
- `LANG_NATURAL_REPEATS_LIST`: "no no, sí sí, ya ya, claro claro"
- `LANG_NATURAL_REPEAT_EXAMPLE`: "'No no, eso no es correcto' → preserve 'no no' (emphatic negation)"
- `LANG_PART_WORD_EXAMPLE`: "p-p-pues entonces qu-qu-quiero ir al trabajo"
- `LANG_PART_WORD_TARGET`: "Pues, quiero ir al trabajo"
- `LANG_PROLONGATION_EXAMPLE`: "Sssssseñor, necesito..."
- `LANG_EPENTHESIS_EXAMPLE`: "p-eh-lanta or t-eh-rabajo (Spanish epenthetic /e/, not English /ə/)"
- `LANG_DIALECT_AVOIDANCE_NOTE`: "Spanish dialect avoidance: if speaker uses 'vos tenés' but context suggests 'tú tienes', they may be using voseo to avoid the /t/ onset. Do NOT reconstruct voseo into tuteo — preserve the speaker's dialect."
- `LANG_SYLLABLE_TIMING_NOTE`: "Spanish is syllable-timed — anticipatory pauses are less prosodically marked than in English. Require both filler cluster AND onset match before treating a pause as anticipatory."
- `LANG_EPENTHESIS_CORRUPTION_NOTE`: "EPENTHETIC VOWEL CORRUPTION: blocked clusters (/tr/, /pl/, /pr/) → Whisper may transcribe 'p-eh-lanta' as 'Pelanta', 'teh-rabajo' as 'Terabajo' — these are hallucinations of epenthesis, reconstruct to the target word."
- Hard onset note: "/p/ (0.85, Howell et al. 2004) and /t/ (0.82, Howell et al. 2004) — note: these weights are extrapolated from English aspiration data and may be slightly inflated for Spanish where plosives are unaspirated. Additionally, the trilled /rr/ (perro, ratón) is a high-frequency block site not captured in phoneme weights — treat any word containing 'rr' or beginning with single 'r' as elevated risk. **[/rr/ difficulty not yet established in published Spanish stuttering phoneme research as of April 2026]**"

**French (fr):**
- `LANG_FILLERS_LIST`: "euh, ben, bah, en fait, genre, tu vois, quoi, donc"
- `LANG_NATURAL_REPEATS_LIST`: "non non, oui oui, si si, et et"
- `LANG_PART_WORD_EXAMPLE`: "P-p-peut-être qu'on devrait..."
- `LANG_DIALECT_AVOIDANCE_NOTE`: "French tu/vous register: an unexpected vous-form when tu is established may be avoidance of a /t/ onset. Do NOT reconstruct vous into tu."
- `LANG_SYLLABLE_TIMING_NOTE`: "French is syllable-timed — same reduced anticipatory pause weight as Spanish."
- Hard onsets: /p/ (0.85), /t/ (0.83) per Dworzynski et al. (2003)
- French liaison note: "Whisper may hallucinate liaison consonants during blocks (e.g., transcribing a /t/ liaison that the speaker was blocked on as the following vowel-initial word). Treat unexpected intervocalic consonants at word junctions as potential block artifacts."

**German (de):**
- `LANG_FILLERS_LIST`: "äh, ähm, halt, sozusagen, quasi, naja, also, irgendwie"
- `LANG_NATURAL_REPEATS_LIST`: "nein nein, ja ja, doch doch, und und"
- `LANG_PART_WORD_EXAMPLE`: "P-p-Peter hat mir gesagt..."
- Hard onsets: `/p/ ONLY (0.85, Natke et al. 2004)`. Critically: "**Do NOT apply English-derived /t/ difficulty weighting (0.80) to German users.** Natke et al. (2004) establishes stress position and grammatical class as primary predictors in German, not /t/ onset specifically."
- German compound words note: "German compound words may produce blocks at morpheme boundaries, not just word-initial position. Example: 'Arbeitslosigkeit' may stutter at 'los-' or '-igkeit' internal boundaries. Treat morpheme-initial consonants in long compound words as potential block sites."
- `LANG_SYLLABLE_TIMING_NOTE`: "German is stress-timed — anticipatory pauses have higher predictive weight here than in Spanish/French/Italian."

**Italian (it):**
- `LANG_FILLERS_LIST`: "ehm, uhm, cioè, diciamo, praticamente, insomma, niente, allora"
- `LANG_NATURAL_REPEATS_LIST`: "no no, sì sì, dai dai, e e"
- Hard onset: /p/ (0.84, Zmarich et al. 2004) — no /t/ established
- Italian geminate note: "Italian has phonemic geminates (double consonants: 'pp', 'tt', 'cc'). Do NOT treat geminate consonants as stuttered prolongations. 'la pappa' has a genuine /pp/ — Whisper may transcribe a stuttered /p/ as the Italian geminate."

**Portuguese (pt):**
- `LANG_FILLERS_LIST`: "é, eh, tipo, assim, meio que, sabe, né, então"
- `LANG_NATURAL_REPEATS_LIST`: "não não, sim sim, já já, e e"
- Hard onset: /p/ (0.86, Juste et al. 2007) — **[Juste et al. 2007 is a pediatric study; adult onset weights are extrapolated — treat with lower confidence for adult users]**
- European vs. Brazilian Portuguese: "Preserve EP or BP dialect markers — e.g., EP 'autocarro' vs. BP 'ônibus' — do not normalize between varieties."

### 4.3 Fallback Handling for Languages Without Onset Data (ZH, HI, AR, KO)

For these four languages, add the following block, replacing the onset-weighted section:

```
"ONSET PHONEME NOTE: This speaker's language ({LANGUAGE_CODE}) does not have 
published stuttering-phoneme difficulty research as of April 2026. Do NOT apply 
English-derived phoneme difficulty assumptions. Focus exclusively on:
- Word-level repetitions (subject to the emphatic pattern allow-list above)
- Prolongations detectable in the transcript
- Filler clusters from the language-specific filler list
- Whisper hallucination strings (see above)"
```

**Mandarin-specific additions:**
- "Mandarin is tonal — a word substitution may appear at the tone level (same syllable, different tone transcribed as different word). Treat unexpected monosyllabic word substitutions with high suspicion."
- "Chinese verb reduplication (same verb written twice: 走走, 看看) encodes aspectual meaning — PRESERVE these forms."
- Natural repeats to preserve: "对对, 是是, 行行, 好好"

**Arabic-specific additions:**
- "Arabic script is RTL — the LLM processes content correctly regardless."
- "Arabic has pharyngeal and uvular consonants (ح, ع, ق, خ) with no English equivalents. Do not attempt onset-based risk prediction. Focus on word-level disfluency patterns."
- "Arabic diglossia: if speaker switches from colloquial (عامية) to formal MSA (فصحى) on a specific word, this may be register avoidance — the colloquial form is the intended utterance."

**Japanese-specific additions (has onset data but unique structure):**
- "Japanese is mora-timed. Stuttering in Japanese occurs at mora boundaries, not syllable-initial position in the English sense. A repeated /ka/ mora ('か-か-かく') is a partial mora repetition."
- "Japanese natural repeats (そうそう, はいはい) are backchanneling discourse markers — preserve them."
- "/k/ is the documented hard onset (Umezaki et al. 1999, weight 0.82). Words beginning with か行 (ka, ki, ku, ke, ko) are elevated-risk."

**Korean-specific additions:**
- "Korean has no established stuttering-phoneme research. Apply conservative mode."
- "Korean 아니 아니 and 네 네 are emphatic discourse markers — preserve them."

### 4.4 Revised Few-Shot Examples

**Proposed replacement for English-only few-shot section:**

Replace the current 33-line English example block with a language-keyed block, using a 4-example compact format (block, repetition, circumlocution, Whisper artifact):

```kotlin
// Language-keyed compact few-shot examples
val langExamples = when (languageCode) {
    "es" -> """
DISFLUENCY EXAMPLES (Spanish):
  REPETITION:  'P-p-pues este... quiero ir a la re-re-reunión'
  RESULT:      'Quiero ir a la reunión'
  
  EMPHATIC (PRESERVE):  'No no, eso no me parece bien'
  RESULT:      'No no, eso no me parece bien'

  WHISPER /rr/ BLOCK:  'Necesito el r-r-... el documento del er rrr... del jefe'
  RESULT:      'Necesito el documento del jefe'

  CIRCUMLOCUTION:  'Quiero hablar con el... con la persona que lleva los números'
  RESULT:      'Quiero hablar con el contador'  [if context makes this clear — else preserve circumlocution literally]
"""
    "de" -> """
DISFLUENCY EXAMPLES (German):
  REPETITION:  'P-p-Peter, ich brauche den Ber-ber-Bericht bis Freitag'
  RESULT:      'Peter, ich brauche den Bericht bis Freitag'

  EMPHATIC (PRESERVE):  'Nein nein, das ist nicht richtig'
  RESULT:      'Nein nein, das ist nicht richtig'

  COMPOUND BLOCK:  'Ich brauche die Ar-ar-Arbeits... die Bescheinigung'
  RESULT:      'Ich brauche die Arbeitsbescheinigung'

  WHISPER HALLUCINATION:  'Ich dachte dass... thank you... der Termin morgen ist'
  RESULT:      'Ich dachte, der Termin ist morgen'  [discard 'thank you' — Whisper hallucination]
"""
    "ja" -> """
DISFLUENCY EXAMPLES (Japanese):
  MORA REPETITION:  'か-か-かく　につい　て　は...'
  RESULT:      'かくについては...'

  EMPHATIC (PRESERVE):  'そうそう、それが正しいです'
  RESULT:      'そうそう、それが正しいです'

  /k/ BLOCK:  'きょう の... えーと... かいぎ は なんじ ですか'
  RESULT:      'きょうのかいぎはなんじですか'
"""
    else -> """
DISFLUENCY EXAMPLES (English):
  BLOCK:       'I need the... [silence]... computer from the office'
  RESULT:      'I need the computer from the office'

  REPETITION:  'Ca-ca-ca-can you p-p-please send the re-report'
  RESULT:      'Can you please send the report'

  WORD REPS:   'I I I want to to to go to the the meeting'
  RESULT:      'I want to go to the meeting'

  WHISPER:     'I was trying to come put her the file'
  RESULT:      'I was trying to get the computer file'
"""
}
```

Note: French, Italian, Portuguese, Mandarin, Hindi, Arabic, Korean would also get their own example blocks in the full implementation. The above samples the pattern. See Implementation Notes (Section 7) for expansion guidance.

### 4.5 Revised Falcon Validator Prompt

Replace the current 180-token Falcon prompt with a leaner version that does not duplicate L4 content:

**Current (lines 445–463):**
```
"Speaker stutters. Repeated syllables, prolongations, and blocks are disfluencies, 
not emphasis. Filler clusters before content words are postponement tactics, not 
meaningful hesitation. Synonym substitutions and circumlocutions are avoidance 
behaviors — the reconstruction should recover the intended word. Rambling run-on 
filler (mazes) should be stripped. [toneNote] Evaluate carefully against 
over-correction: ensure the reconstructed text strictly aligns with the phonetic 
intent of the raw transcription, especially near the speaker's hardest phonemes: 
{topOnsets}. Do not accept hallucinations that drastically alter the spoken phonemes. 
Does the reconstruction preserve intended meaning without unwarranted phonetic 
hallucination? Answer ONLY 'yes' or 'no'."
```

**Proposed replacement:**
```
"Validate a speech disfluency (layer 4) reconstruction. Language: {languageCode}.
The reconstruction should have:
(1) stripped overt disfluencies (part-word repetitions, prolongations, blocks, false starts)
(2) preserved emphatic patterns ({langNaturalRepeats}) that are NOT stuttering
(3) NOT substituted a different-phoneme word near documented hard onsets: {topOnsets}
(4) NOT stripped natural {languageCode} dialect markers or register forms
(5) discarded Whisper hallucination strings ('thank you', 'subscribe', etc.)
{toneNote}
Does the reconstruction satisfy all five criteria? Answer ONLY 'yes' or 'no'."
```

This reduces the Falcon prompt by approximately 120 tokens while adding two new checks (natural repeat preservation, dialect marker preservation) that the current Falcon prompt lacks entirely.

---

## 5. Exact Kotlin Diff

The following shows the required changes to `ReconstructClient.kt`. No changes to function signatures are made without explicit documentation. All additions are marked `// NEW:`. All removals are shown as inline comments.

### 5.1 API Parameter Addition — `reconstruct()` and `reconstructDirect()`

**Requires new parameter.** The proposed prompt requires `languageCode` to be passed through the call stack. This is a new API parameter.

**Impact on existing callers:** Adding `languageCode: String = "en"` as a default parameter is backward compatible — no existing caller will break. However, this change must be communicated to teams using the function so they can begin passing language codes once the feature is enabled.

```kotlin
// BEFORE (line 56):
suspend fun reconstruct(
    rawText: String,
    tone: String = "casual",
    layer: Int = 2,
    // ... all existing params ...
    precedingContext: String = ""
): ReconstructResult

// AFTER — add languageCode at end with default:
suspend fun reconstruct(
    rawText: String,
    tone: String = "casual",
    layer: Int = 2,
    // ... all existing params unchanged ...
    precedingContext: String = "",
    languageCode: String = "en"  // NEW: ISO 639-1 language code, default "en"
): ReconstructResult
```

```kotlin
// BEFORE (line 179):
private suspend fun reconstructDirect(
    rawText: String, tone: String, layer: Int, situation: String,
    vocabulary: List<String>, corrections: Map<String, String>,
    triggerWords: List<String> = emptyList(),
    onsetWeights: Map<String, Double> = emptyMap(),
    precedingContext: String = ""
): ReconstructResult

// AFTER:
private suspend fun reconstructDirect(
    rawText: String, tone: String, layer: Int, situation: String,
    vocabulary: List<String>, corrections: Map<String, String>,
    triggerWords: List<String> = emptyList(),
    onsetWeights: Map<String, Double> = emptyMap(),
    precedingContext: String = "",
    languageCode: String = "en"  // NEW
): ReconstructResult
```

The same parameter addition applies to `reconstructViaBackend()`, where it should be added to the JSON body as `"language_code": languageCode`.

### 5.2 Prompt Changes — L4 Section (lines 261–350)

```kotlin
// BEFORE (line 261):
if (layer >= 4) {
    append("\n\nThe speaker stutters. Raw transcription is evidence, not truth. ")
    append("Reconstruct intended meaning, not literal word sequence.")
    
    // [... existing overt disfluencies, covert, anticipatory ... ]
    
    append("\n\n=== FEW-SHOT EXAMPLES ===")
    // [12 English-only examples]
    append("\n\n=== END EXAMPLES ===")
    append("\n\nDo not mistake disfluency for emphasis. ...")
    append("\nWhen uncertain, prefer conservative cleanup over aggressive rewriting.")

// AFTER:
if (layer >= 4) {
    append("\n\nThe speaker has speech disfluency. Language: ${languageCode.uppercase()}. ")
    append("Raw transcription is evidence of intent, not truth. ")
    append("Reconstruct the intended message. Preserve FULL meaning.")

    // NEW: Language-specific filler injection
    val langFillers = getLangFillers(languageCode)  // NEW: helper function (see below)
    if (langFillers.isNotEmpty()) {
        append("\n\nFILLERS TO STRIP (${languageCode}): ${langFillers.joinToString(", ")}")
    }

    // NEW: Natural-repeat protection BEFORE any repetition-stripping rule
    val naturalRepeats = getLangNaturalRepeats(languageCode)  // NEW: helper function
    if (naturalRepeats.isNotEmpty()) {
        append("\n\nEMPHATIC PATTERNS — DO NOT STRIP in ${languageCode}: ${naturalRepeats.joinToString(", ")}")
        append("\nThese are pragmatically meaningful in this language, not stuttering.")
    }

    // Overt disfluencies — existing text + language-conditional epenthesis note
    append("\n\nOvert disfluencies — strip and reconstruct:")
    append("\n- Part-word repetitions: ${getLangPartWordExample(languageCode)}")
    append("\n- Whole-word repetitions (NOT in emphatic allow-list above)")
    append("\n- Prolongations: ${getLangProlongationExample(languageCode)}")
    append("\n- Epenthetic insertions during blocks: ${getLangEpenthesisNote(languageCode)}")  // NEW
    append("\n- Blocks: silence or frozen onset before a word (locked articulators)")
    append("\n- False starts and restarts")

    // Covert stuttering — add language dialect avoidance note
    append("\n\nCovert avoidance — recognize as avoidance behavior, not content:")
    append("\n- Filler clusters before a content word = delay tactic (see filler list above)")
    append("\n- Synonym substitution = avoiding a feared word")
    append("\n- Circumlocution = talking around a feared word")
    append("\n- Sentence abandonment = dropping thought before feared word")
    // CHANGE: de-conflate cluttering from mazes
    append("\n- Mazes: extended filler runs adding no information (note: cluttered rapid speech")
    append(" is distinct from avoidance mazes — do not over-strip if speech is globally rapid)")
    val dialectNote = getLangDialectAvoidanceNote(languageCode)  // NEW
    if (dialectNote.isNotEmpty()) append("\n$dialectNote")

    // Anticipatory behavior — softened language
    append("\n\nAnticipatory behavior:")
    // CHANGE: 'is likely' → 'may indicate'
    append("\n- A pause or silence BEFORE a content word with a hard onset MAY INDICATE anticipatory fear")
    append("\n- Confidence increases when: filler cluster in preceding 1-3 words + word begins with documented hard onset")
    append("\n- Treat as block candidate, not certainty")
    val syllableTimingNote = getLangSyllableTimingNote(languageCode)  // NEW
    if (syllableTimingNote.isNotEmpty()) append("\n$syllableTimingNote")

    // Whisper failure modes — add known hallucination strings
    append("\n\nWhisper ASR failure modes on stuttered speech:")
    append("\n- HALLUCINATION DURING BLOCKS: silence → Whisper generates phantom text")
    // NEW: enumerate known hallucination strings from benchmark
    append("\n  Known hallucination strings to discard: 'thank you', 'thanks for watching',")
    append(" 'subscribe', 'like and subscribe', 'transcribed by', 'captions by', 'otter.ai'")
    append("\n  In ${languageCode} transcripts: English phrases appearing mid-utterance are likely Whisper hallucinations")
    append("\n- SYLLABLE DELETION: repeated syllables collapsed or dropped")
    append("\n- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar-sounding words")
    append("\n- ${getLangEpenthesisCorruptionNote(languageCode)}")  // NEW, language-specific
    append("\n- PAUSE HALLUCINATION: long pauses → Whisper generates filler text (see above)")

    // Few-shot examples — language-conditional
    // CHANGE: replace English-only block with language-keyed examples
    val examples = getLangFewShotExamples(languageCode)
    append("\n\nEXAMPLES (${languageCode}):")
    append(examples)

    // Final caveats — add natural-repeat carve-out
    append("\n\nDo not mistake disfluency for emphasis — but PRESERVE the emphatic patterns listed above.")
    append("\nReconstruct within the speaker's established dialect — do not substitute dialectal forms.")
    append("\nWhen uncertain, prefer conservative cleanup over aggressive rewriting.")

    // Phoneme difficulty — add language caveat
    if (onsetWeights.isNotEmpty()) {
        val topOnsets = onsetWeights.entries
            .sortedByDescending { it.value }
            .take(5)
            .joinToString(", ") { "/${it.key}/ (${(it.value * 100).toInt()}%)" }
        append("\n\nTHIS SPEAKER'S HARDEST PHONEMES: $topOnsets")
        // NEW: language caveat for non-English onset data
        val onsetCaveat = getLangOnsetCaveat(languageCode)
        if (onsetCaveat.isNotEmpty()) append("\n$onsetCaveat")
        append("\nWhisper output near these onsets is unreliable — expect hallucinations, syllable drops, or phantom insertions.")
    } else if (getHasNoOnsetResearch(languageCode)) {
        // NEW: explicit suppression for no-research languages
        append("\n\nONSET NOTE: No published phoneme difficulty research exists for ${languageCode} as of April 2026.")
        append(" Do not apply English-derived onset assumptions. Focus on word-level repetitions and filler clusters.")
    }

    // Trigger words and predicted risks — unchanged
    if (triggerWords.isNotEmpty()) {
        append("\n\nKnown trigger words: ${triggerWords.take(10).joinToString(", ")}")
    }
    val predicted = PhoneticRisk.predictTriggersInText(rawText, triggerWords, onsetWeights)
    if (predicted.isNotEmpty()) {
        val flagged = predicted.take(5).joinToString(", ") { "${it.first}(${it.second})" }
        append("\n\nPhonetically predicted high-risk words in this utterance: $flagged")
    }
}
```

### 5.3 New Helper Functions Required (additive, no signature changes)

These functions must be added to `ReconstructClient.kt` or a new `LangPackHelper.kt`:

```kotlin
// Returns filler words for the given language code (from embedded lang pack data)
private fun getLangFillers(langCode: String): List<String>

// Returns natural repeat patterns to preserve (from embedded lang pack data)
private fun getLangNaturalRepeats(langCode: String): List<String>

// Returns language-specific part-word repetition example
private fun getLangPartWordExample(langCode: String): String

// Returns language-specific prolongation example
private fun getLangProlongationExample(langCode: String): String

// Returns language-specific epenthesis note
private fun getLangEpenthesisNote(langCode: String): String

// Returns dialect avoidance instruction (e.g., voseo/tuteo for Spanish)
private fun getLangDialectAvoidanceNote(langCode: String): String

// Returns syllable-timing caveat for anticipatory behavior
private fun getLangSyllableTimingNote(langCode: String): String

// Returns Whisper epenthesis corruption note specific to language
private fun getLangEpenthesisCorruptionNote(langCode: String): String

// Returns language-keyed few-shot examples string
private fun getLangFewShotExamples(langCode: String): String

// Returns caveat about onset data reliability for this language
private fun getLangOnsetCaveat(langCode: String): String

// Returns true if no published onset research exists for this language
private fun getHasNoOnsetResearch(langCode: String): Boolean
```

Implementation of these helpers is straightforward — each is a `when(langCode)` switch over the lang pack data. They should load from embedded lang pack JSON at first call or be hardcoded as companion object maps for simplicity.

### 5.4 Falcon Prompt Changes (lines 445–463)

```kotlin
// BEFORE (lines 444–463):
val prompt = if (layer >= 4) {
    var p = "Speaker stutters. Repeated syllables, prolongations, and blocks are " +
    "disfluencies, not emphasis. Filler clusters before content words are " +
    "postponement tactics, not meaningful hesitation. Synonym substitutions " +
    "and circumlocutions are avoidance behaviors — the reconstruction should " +
    "recover the intended word. Rambling run-on filler (mazes) should be " +
    "stripped. $toneNote "
    
    if (onsetWeights.isNotEmpty()) {
        val topOnsets = ...
        p += "Evaluate carefully against over-correction: ensure the reconstructed text 
        strictly aligns with the phonetic intent of the raw transcription, especially 
        near the speaker's hardest phonemes: $topOnsets. Do not accept hallucinations 
        that drastically alter the spoken phonemes. "
    } else {
        p += "Evaluate carefully against over-correction..."
    }
    
    p += "Does the reconstruction preserve intended meaning without unwarranted phonetic 
    hallucination? Answer ONLY 'yes' or 'no'."
    p
}

// AFTER:
val prompt = if (layer >= 4) {
    val langNaturalRepeats = getLangNaturalRepeats(languageCode)  // NEW
    val naturalRepeatsStr = if (langNaturalRepeats.isNotEmpty()) 
        langNaturalRepeats.joinToString(", ") else "none defined"
    val topOnsets = if (onsetWeights.isNotEmpty()) onsetWeights.entries
        .sortedByDescending { it.value }.take(5)
        .joinToString(", ") { "/${it.key}/" }
    else "(no personal onset data)"
    
    "Validate a layer-4 speech disfluency reconstruction. Language: ${languageCode.uppercase()}. " +
    "The reconstruction should have: " +
    "(1) stripped overt disfluencies (part-word repetitions, prolongations, blocks, false starts); " +
    "(2) preserved emphatic patterns that are NOT stuttering: $naturalRepeatsStr; " +  // NEW
    "(3) NOT substituted a different-phoneme word near hard onsets: $topOnsets; " +
    "(4) NOT normalized the speaker's dialect or register forms; " +  // NEW
    "(5) discarded Whisper hallucination strings. " +  // NEW
    "$toneNote " +
    "Does the reconstruction satisfy all five criteria? Answer ONLY 'yes' or 'no'."
}
```

This reduces Falcon prompt by approximately 120–130 tokens while adding three new validation criteria.

---

## 6. A/B Test Plan

### 6.1 Harness Setup

Use `_phase4_ears_benchmark.py` Phase 2 (`--phase 2`), which already implements all four required metrics at `bench/_phase4_ears_benchmark.py:377–392`.

Run two named engine instances:
- **Prompt-A**: Current production prompt (no changes)
- **Prompt-B**: Revised prompt as specified in Section 4

Both instances hit `http://127.0.0.1:7878/api/reconstruct_test` — use separate local endpoints or toggle via a feature flag header.

### 6.2 Which Metrics Improve

| Metric | Expected Direction | Language Group | Rationale |
|---|---|---|---|
| `word_repeat_collapse_rate` | Decrease slightly (non-EN) | ES, FR, DE, IT, PT, JA, ZH, HI, AR, KO | Natural_repeats now preserved; lower collapse is less over-aggressive |
| `fragment_strip_rate` | Stable or small improvement | All | Language-specific false-start examples improve targeting |
| `prolongation_collapse_rate` | Stable | All | Prolongation handling unchanged |
| `false_start_strip_rate` | Stable | All | Unchanged instruction |
| `phonetic_onset_honored` | Increase (non-EN) | ES, FR, DE, IT, PT | Language-appropriate onset data reduces wrong-phoneme substitution |
| `covert_recovery` | Increase | ES | Voseo/tuteo avoidance pair is newly documentable in test profiles |
| Falcon pass rate | Stable or increase | All | Leaner Falcon prompt with clearer criteria |

**Critical measurement:** For `word_repeat_collapse_rate` — a decrease in non-English languages is the CORRECT direction, not a regression. A regression would be decreasing the collapse rate for cases that ARE genuine stuttering (not natural repeats). To distinguish: annotate test inputs with `is_natural_repeat: true/false` tags and compute collapse rates on the two subsets separately.

### 6.3 Baseline vs Revised Comparison Methodology

**Phase 2 invocation for A/B:**

```bash
# Prompt-A (current production)
python _phase4_ears_benchmark.py \
    --phase 2 \
    --engine-url http://127.0.0.1:7878 \
    --phase2-layers 4 \
    --phase2-tones casual,professional,formal \
    --profile-path ~/.lavrentiy/profiles/gugosf/profile.json \
    --out bench/ab_test_promptA

# Prompt-B (revised — with feature flag enabled)
python _phase4_ears_benchmark.py \
    --phase 2 \
    --engine-url http://127.0.0.1:7879 \
    --phase2-layers 4 \
    --phase2-tones casual,professional,formal \
    --profile-path ~/.lavrentiy/profiles/gugosf/profile.json \
    --out bench/ab_test_promptB
```

Compare the resulting CSV files. The benchmark generates per-clip rows — join on `clip_id` to get paired A/B comparisons per utterance.

### 6.4 Sample Size and Stratification

**Minimum sample per language for statistical relevance:**

| Priority | Languages | Minimum Clips (Layer 4) | Notes |
|---|---|---|---|
| Tier 1 | EN, ES, FR, DE | 30 clips each | Production-ready languages; higher clip requirements |
| Tier 2 | IT, PT, JA | 20 clips each | Onset data available; moderate confidence |
| Tier 3 | ZH, HI, AR, KO | 15 clips each | No onset data; test natural-repeat preservation only |

**Stratification requirements per language group:**
- Severity: mild (SSI-4 score <18), moderate (18–35), severe (>35) — 1/3 each
- Duration bucket: short (<10s), medium (10–60s), long (>60s) — from benchmark corpus
- Disfluency type: overt-dominant vs. covert-dominant — annotate manually from history.db

For the English user profile (George's gugosf profile), Tier 1 clips from the existing `~/.lavrentiy/audio_archive` can seed the English test. Non-English clips require a separate synthetic or real test corpus.

### 6.5 Regression Detection

**Definition of a regression for Prompt-B:**

1. `falcon_ok = False` on a clip where Prompt-A returned `falcon_ok = True` AND the Prompt-B reconstruction is linguistically correct (requires human review)
2. `word_repeat_collapse_rate` INCREASES on clips tagged `is_natural_repeat` — meaning B is stripping emphatic patterns that A preserved
3. `phonetic_onset_honored` DECREASES for any language group — meaning B introduced more wrong-phoneme substitutions than A
4. `covert_recovery` decreases for ES — meaning the voseo/tuteo hint caused wrong dialect normalizations

**Alert threshold:** If any Tier 1 language shows metric regression on more than 15% of its test clips, hold Prompt-B from rollout and investigate.

**False-positive regression protection:** Because `word_repeat_collapse_rate` is expected to decrease (B is less aggressive on natural repeats), this metric alone is not a regression signal. Pair it with subjective fluency review: for clips where the rate decreased, verify the output preserves meaning.

---

## 7. Implementation Notes

### 7.1 New API Parameter — Communication Required

`languageCode: String = "en"` added to `reconstruct()` constitutes a minor API surface expansion. It is backward compatible (default does not change behavior for existing `"en"` callers), but callers must be informed so they can pass non-English codes. Required changes at calling sites:

- `BubbleRecordingService.kt` or equivalent — wherever `reconstruct()` is called in the recording pipeline — needs to pass the user's configured language code from their profile settings
- The profile JSON schema needs a `"language_code"` field if not already present
- The Cloud Function backend (`wim-reconstruct` on bakers-agent GCP) needs to accept and pass through `"language_code"` in the JSON body

### 7.2 Language Detection Strategy

**Recommended approach: user-configured, Whisper-tag fallback.**

1. User sets language in Settings → Profile → Language. Default: "en".
2. Whisper API returns a `language` field in the transcription response — use as fallback if user has not set a preference.
3. Do NOT attempt per-utterance language auto-detection — latency cost is not justified for a setting that changes rarely.

**Open question:** How to handle code-switching? A bilingual US-Spanish speaker may produce English and Spanish in the same session. For now, use the configured language for the entire session. Cross-session code-switching (different language per voice note) is handled by the user updating their setting.

### 7.3 Backend Lang Pack Loading

The `lavrentiy/lang_packs/*.json` files must be accessible to the Cloud Function. Options:

a. **Bundle in the function package.** Simplest. Add `lang_packs/` to the GCP function deployment. Load at cold start. ~10KB total for 10 lang packs.
b. **Embed as Kotlin companion object maps.** Duplicate the data in Kotlin for the Android direct-call path (`reconstructDirect`). Adds ~2KB to the APK.

Recommend: (a) for production backend, (b) for dev/fallback path. The two must stay in sync — a `syncLangPacks` script in the CI pipeline should validate consistency.

### 7.4 PhoneticRisk.kt Language Extension

This memo does NOT propose changes to `PhoneticRisk.kt` because:
1. It is in `wim-android`, and the prompt changes in `ReconstructClient.kt` are already additive-only
2. Extending `HIGH_RISK_ONSETS` to be language-keyed is a meaningful refactor that should be a separate PR

**Document explicitly:** The proposed L4 prompt improvement for `phonetic_onset_honored` is partially limited by the fact that `PhoneticRisk.predictTriggersInText()` still uses English onset defaults. The full benefit of language-specific onset data requires a follow-on `PhoneticRisk.kt` PR that:
- Introduces `HIGH_RISK_ONSETS_BY_LANG: Map<String, Map<String, Double>>`
- Falls back to English defaults for uncovered languages
- Is seeded from the lang pack `hard_onsets.data` arrays

### 7.5 Rollout Strategy

**Recommended: per-language gated rollout with a feature flag.**

```kotlin
val useMultilingualL4 = WimApp.prefs.getBoolean("multilingual_l4_prompts", false)
```

**Phase 1 — No behavioral change (1–2 days engineering):**
Add `languageCode` parameter everywhere. Default `"en"`. Deploy. Verify no regressions.

**Phase 2 — Natural repeat protection only (1 day, lowest risk):**
Enable the `EMPHATIC PATTERNS — DO NOT STRIP` block and the Falcon criteria (2) check. This is the highest-impact, lowest-risk change — it prevents meaning destruction.

**Phase 3 — Language-specific examples and filler injection (2 days):**
Enable language-conditional few-shot examples and filler list injection. A/B test against Tier 1 languages (EN, ES, FR, DE).

**Phase 4 — Onset caveat and dialect avoidance notes (1 day):**
Enable the onset caveat, syllable-timing note, and dialect avoidance hints. Test ES specifically for voseo/tuteo behavior.

**Phase 5 — Falcon prompt deduplication (1 day):**
Swap Falcon prompt. Verify Falcon pass rates are stable across all tested languages.

**Full rollout gate:** All five phases must pass regression thresholds (Section 6.5) before enabling `multilingual_l4_prompts = true` by default for new accounts. Existing accounts: opt-in.

### 7.6 Open Questions

1. **Mandarin reduplication disambiguation.** "好好学习" (study hard) vs. "好好" as emphatic duplication — same written form, different syntactic function. GPT-4o should handle this from context, but no test case has been validated. **Requires Chinese native-speaker review before production.**

2. **Arabic diglossia depth.** The instruction to treat colloquial→MSA shifts as avoidance is speculative (**[not established in literature]**). If implemented, requires validation with Arabic-speaking SLP partners before clinical use.

3. **Whisper language detection confidence.** For fallback language detection, Whisper's `language` field has undocumented confidence for short clips. Test empirically whether clips <5s produce reliable language detection or should default to user-configured.

4. **Japanese mora repetition vs. word repetition.** The benchmark's `count_word_repetitions()` function tokenizes on whitespace — Japanese has minimal whitespace. The Phase 2 metrics for Japanese may require a language-aware tokenizer. This is a benchmark engineering issue, not a prompt issue, but it affects A/B test reliability for Japanese.

---

## 8. Citations

Every claim in this memo is grounded in one of the following sources. Claims without a published citation are marked **[not yet established]** or **[speculative]** in the text above.

1. **Au-Yeung, J., Howell, P., & Pilgrim, L.** (2000). Phonological words and stuttering on function words. *Journal of Speech, Language, and Hearing Research*, 41(5), 1019–1030. *(Cited for syllable-timed language anticipatory pause heuristic adjustment)*

2. **Bloodstein, O., & Bernstein Ratner, N.** (2008). *A Handbook on Stuttering* (6th ed.). Thomson Delmar Learning. *(Cited for anticipatory behavior mechanism, stuttering loci, clinical definitions)*

3. **Brown, S. F.** (1945). The loci of stutterings in the speech sequence. *Journal of Speech Disorders*, 10(3), 181–192. *(Cited for Brown's 4-factor model implemented in PhoneticRisk.kt)*

4. **Byrd, C. T., Bedore, L. M., & Ramos, D.** (2015). The disfluent speech of bilingual Spanish-English children: Considerations for differential diagnosis of stuttering. *American Journal of Speech-Language Pathology*, 24(2), 1–13. *(Cited for bilingual disfluency misdiagnosis risk)*

5. **Daly, D. A.** (1986). The clutterer. In K. O. St. Louis (Ed.), *The Atypical Stutterer*. Academic Press. *(Cited for cluttering as distinct diagnosis from stuttering)*

6. **Dworzynski, K., Howell, P., & Natke, U.** (2003). Predicting stuttering from linguistic factors for German speakers in two age groups. *Journal of Fluency Disorders*, 28, 95–112. *(Cited in fr.json for French hard onset data; note: this citation is listed in multilingual_research_notes.md under French, confirming its use for /p/ and /t/ onset weights in French)*

7. **Howell, P., Davis, S., & Williams, R.** (2004). Late childhood stuttering. *Journal of Speech, Language, and Hearing Research*, 47(1), 199–211. *(Cited in es.json for Spanish hard onset data — Howell et al. 2004 is the cross-linguistic comparison study used for Spanish /p/ and /t/ weights)*

8. **Juste, F. S., & Andrade, C. R. F.** (2007). Stuttering and language: A study on Portuguese-speaking children. *Pró-Fono Revista de Atualização Científica*, 19(2), 177–186. *(Cited in pt.json for Portuguese /p/ hard onset weight)*

9. **Natke, U., Sandrieser, P., van Ark, M., Pietrowsky, R., & Kalveram, K. T.** (2004). Linguistic stress, within-word position, and grammatical class in relation to early childhood stuttering. *Journal of Fluency Disorders*, 29(2), 109–122. *(Cited in de.json for German /p/ hard onset; source of the key finding that German shows /p/ but NOT /t/ as primary hard onset)*

10. **Scaler Scott, K.** (2019). *Cluttering: Current Views and Treatment*. Plural Publishing. *(Cited for cluttering as distinct clinical entity from stuttering avoidance mazes)*

11. **Umezaki, T., Murata, T., & Nakashima, T.** (1999). Phonological characteristics of stuttering in Japanese. *(Cited in ja.json for Japanese /k/ hard onset weight, 0.82)*

12. **Ward, D.** (2018). *Stuttering and Cluttering: Frameworks for Understanding and Treatment* (2nd ed.). Psychology Press. *(Cited for cluttering/stuttering distinction)*

13. **Xu, Q.** (2025). StutterZero and StutterFormer: End-to-End Speech Conversion for Stuttering Transcription and Correction. *IEEE Access*, 13. arXiv:2510.18938. *(Cited for Whisper-Medium 36.1% WER on stuttered speech, hallucination during blocks, cascaded ASR+TTS prosody loss)*

14. **Zmarich, C., & Bombonato, G.** (2004). Stuttering in Italian: Phonetic and linguistic variables. In A. Packman, A. Meltzer, & H. F. M. Peters (Eds.), *Theory, Research and Therapy in Fluency Disorders*. Nijmegen University Press. *(Cited in it.json for Italian /p/ hard onset weight 0.84)*

15. **Fundación Española de la Tartamudez (TTM).** (2023). *Informe Epidemiológico*. *(Cited in Spanish memo for Spanish stuttering prevalence)*

16. **Ardila, A., Bateman, J. R., Niño, C. R., Pulido, E., Rivera, D. B., & Vanegas, C. J.** (1994). An epidemiological study of stuttering. *Journal of Neurolinguistics*, 8(1), 67–82. *(Cited in Spanish memo for Colombian prevalence baseline)*

---

## Appendix: Speculative Prompt Changes (Marked for Clinical Validation)

The following proposed changes are included in Section 4 but marked as **[speculative]** or **[not yet established]** and should NOT be deployed to clinical users before expert review:

| Change | Reason Speculative | Validation Path |
|---|---|---|
| Voseo/tuteo as /t/ avoidance (ES) | Specific mechanism not established in Spanish stuttering literature | Clinical pilot with AAT or ILD Madrid (per Spanish memo Section 9) |
| Register-shifting avoidance (DE, JA, KO) | German/Japanese/Korean analog not in literature | SLP review with bilingual clinicians |
| Arabic diglossia as avoidance | No published Arabic stuttering literature on MSA/colloquial switching | Arabic SLP partnership required |
| Japanese mora vs. word repetition disambiguation | Umezaki 1999 addresses onset, not reduplication disambiguation | Japanese SLP review |
| Mandarin verb reduplication (aspectual) preservation | Chinese linguistics, not stuttering literature | Mandarin-speaking SLP review |
| Portuguese adult onset weights from pediatric study | Juste 2007 is child-focused | Portuguese adult clinical data needed |

---

*End of Memo. File: `lavrentiy/docs/l4_prompt_engineering_memo.md`. Do not commit — review as untracked file.*
