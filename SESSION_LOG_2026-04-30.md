# Session log — April 30, 2026 — Lav: L1-pack expansion (3→10), WiM parity port, wim-reconstruct deploy

Single-day arc started with a deep reread of both repos' READMEs, broke into per-layer audits, ended with the L1-transfer pack architecture expanded from 3 supported languages to 10 plus a parity port from WiM to Lav. Cross-cutting work (patent prior-art audit, USPTO filing-requirements verification, grant strategy framing, two key research papers identified) lives mostly in WiM `SESSION_LOG_2026-04-30.md` (continued, evening) — the bubble + clarifier + grant pitch is bubble-centric, so the WiM log is the canonical home. Lav-relevant pieces of those threads recapped here.

---

## 1. PhoneticMatcher port — WiM → Lav

WiM had `PhoneticMatcher.kt` (Apache Commons Codec Double Metaphone) firing at L1 and L2+ paths to swap ASR-misheard words against the user's vocabulary when the misheard word's onset is in the high-risk onset map. Lav had no equivalent — closest was the L4 onset-weight prediction model, which is a different feature (predicts difficulty per phoneme rather than swapping phonetic neighbors).

Built `phonetic_match()` in `lavrentiy.py` mirroring WiM's Kotlin implementation:

- `_PHONETIC_MIN_WORD_LENGTH = 3` (matches WiM)
- `_PHONETIC_HIGH_RISK_THRESHOLD = 0.5` (matches WiM)
- First-letter guard against b/p, t/d, k/g, m/n Double-Metaphone collisions ("bitch" vs "push" both PX, "tin" vs "din" both TN — without this guard the swap fires wrong)
- Casing rule: lowercase-input → lowercase-swap, uppercase-input → uppercase-swap, mixed → vocab form
- Defensive import: `try: from metaphone import doublemetaphone; except ImportError: _doublemetaphone = None`. Engines bundled before metaphone landed in `Lavrentiy.spec` no-op gracefully.

11 smoke tests pass: lowercase preserved, mixed input, ALL CAPS, no swap when no hard-onset hit, vocab-already-correct, onset-gate-blocks-when-missing, empty-weights-match-all, first-letter-guard, empty-vocab, punctuation preserved, metaphone-unavailable-no-op.

**Initial gate: L1+ all layers.** Operator pushback ("I set it only for L2 and L3") restricted to `if 2 <= current_layer <= 3` — same gate as WiM after parity revert. Rationale: at L1 the swap goes straight to paste with no validator (a wrong-direction collision lands in the user's text field); at L4 Sonnet ext-think reasons through phonetic context with the rich onset-weight prompt block instead. The swap pays off only when GPT sees the cleaner input, which is L2/L3.

`NATURAL_REPEATS` expanded with the 7 emphatic doublings WiM had: `really really`, `many many`, `much much`, `right right`, `sure sure`, `okay okay`, `just just`. Lav's `(?:\s+\1){2,}` 3+ threshold already protected 2× emphatic, so these guard the 3+ case (e.g. "really really really" stays).

`Lavrentiy.spec` updated to include `metaphone` in the `collect_all` PyInstaller loop so future installer rebuilds bundle it.

**Commits:**
- `4afdc34` — WiM parity: PhoneticMatcher + emphatic NATURAL_REPEATS
- `ea5007d` — phonetic_match: gate to L2/L3 only

---

## 2. L2 reconstruction layer audit

Operator request: full breakdown of the L2 layer across both apps. Mapped:

- **ASR source** — whisper-tiny.en local on WiM / cloud whisper-1 default on Lav since April 26 toggle / cloud `gpt-4o-transcribe` as L2 fallback in WiM, `whisper-1` everywhere in Lav
- **Pre-LLM strip layers** — Whisper hallucination filter (47 patterns Lav, 42 WiM), DisfluencyFilter 6-step pipeline (stutter fragments with/without space, word reps, phrase reps, fillers, false starts, prolongations), profile corrections (regex-based at L2+), PhoneticMatcher (now L2/L3 in both), repunctuate (deterministic capitalization + terminal punctuation for local ASR output)
- **LLM call** — GPT-4o, temperatures per tone (formal 0.1, professional 0.15, casual 0.35, friend 0.4), max_tokens ~1000-1024, 60s cloud timeout
- **Prompt ingredients (~20 items)** — ALWAYS RESTATE block, audience-context block, L1-transfer pack injection (russian/spanish/mandarin then), domain pack injection (legal/medical/finance/sf_pro/hipaa), rate-gap signal, regenerate-as-negative, self-correction canonical overwrite ("I mean"/"actually"), Strunk & White prose rules, slang preservation list, anti-censorship instruction, bilingual EN/RU sniffer (Lav-only), per-language fillers/natural-repeats from lang_packs, Whisper confidence signals (silently dead at L2 when local ASR is in use)
- **Post-LLM checks** — LLM leak filter (refusal patterns), length explosion guard (3× or 1/3 of input), critical token retention (numbers/dollars/percents), Falcon validation via Haiku 4.5 (cross-vendor) or GPT-4o fallback
- **Output handling** — accessibility ACTION_SET_TEXT injection, smart-spacing, hint-text equality guard (Samsung Messages "Type a message" placeholder), SEND-ready countdown, auto-send Send-button click

### Surfaced parity gaps

| Capability | Lav | WiM |
|---|---|---|
| PhoneticMatcher gate | L4+ only (pre-port) | L1+L2+ (pre-sync) |
| NATURAL_REPEATS list | 22 entries | 29+ entries (incl. emphatic doublings) |
| Bilingual EN/RU sniffer (Cyrillic detect → "speaker is bilingual EN/RU" prompt note) | Yes (`lavrentiy.py:2794-2796`) | No |
| L2 cloud ASR fallback model | `whisper-1` | `gpt-4o-transcribe` (no `verbose_json`) |
| Hallucination pattern count | 47 | 42 |
| Critical-token regex | longer / more precise | simpler |

Of these: PhoneticMatcher gate + NATURAL_REPEATS got synced this session. Bilingual sniffer + cloud fallback model + hallucination patterns + critical-token regex remain unsynced. Captured in operator's parity-rule memory `feedback_lav_wim_parity.md`.

---

## 3. L1-pack expansion — 3 → 10 languages

Operator authorized full scope ("seven hours, take them as much as you'd like, more if needed, let me know before push and commit"). Authored 7 new packs from `lavrentiy/docs/L1_Transfer_Markers_in_Written_English.md` — the 40-page Gemini-generated research paper covering all 10 target languages with marker tables.

| Language | Markers | Citation depth |
|---|---|---|
| Hindi | 10 | Sailaja 2009, Mehrotra 2003, Lange 2007, Kachru 1980, Fuchs 2012 |
| Arabic | 9 | QCAW corpus, Hermas 2014, Hyland, Dafouz-Milne |
| Farsi | 9 | Daghbandan 2023, Talebi 2014 |
| French | 9 | Granger 1998, Paquot 2013, Hendriks 2005, Larsson 2020 |
| German | 9 | Hladka 2013, Larsson 2020 |
| Korean | 9 | Lardiere 2009, Lee 2019, Kim 2022, Hu 2018, Ryoo 2013, Lyu & Wu 2017 |
| Japanese | 9 | Ryu 2015, Nakayama 2020, Sugaya 2013, Baroni 2023, Lardiere 2009 |

Per-pack format identical to existing russian/spanish/mandarin: `{id, category, mechanism, examples, prompt_hint, citation}`. Notes field captures typology summary (e.g., "Indian English is an institutionalized L2 variety with codified divergences from British/American norms; substrate influence from Indo-Aryan and Dravidian families").

**Distributed to 4 destinations, MD5 byte-identical across all 4:**

1. `lavrentiy/l1_packs/` — desktop loader source
2. `lavrentiy/wim/api/l1_packs/` — Cloud Function backend (wim-reconstruct deploy source)
3. `wim-android/app/src/main/assets/l1_packs/` — WiM Android APK assets
4. `bakers-agent/wim-l1-guess-v1/l1_packs/` — auto-detect Cloud Function deploy source

Total prompt-injection footprint across the 7 new packs: ~17,500 chars when fully loaded.

**No code changes needed in Kotlin or Python helpers.** `BUILTIN_KEYS` (line 47-51 of `l1_pack.py`) and `LANG_DISPLAY_NAMES` (line 34-45) already enumerated all 10 languages from initial scaffolding. Helper code was forward-compat from day one; only the JSON content was missing.

Lav loader smoke test (each pack loads + builds prompt injection):

```
hindi: 10 markers, 2419 prompt chars, OK
arabic: 9 markers, 2593 prompt chars, OK
farsi: 9 markers, 2321 prompt chars, OK
french: 9 markers, 2573 prompt chars, OK
german: 9 markers, 2617 prompt chars, OK
korean: 9 markers, 2389 prompt chars, OK
japanese: 9 markers, 2647 prompt chars, OK
```

Operator's commit `2da039b` "Add L1 language marker packs and API copies" captured the Lav-side files (l1_packs/ + wim/api/l1_packs/). WiM-side files committed by operator alongside parallel-session bubble work in `06ae954`. Bakers-agent files committed by Claude in `df95029` on `feat/l1-packs` (surgical add-only — left parallel-session bakers-agent work untouched).

---

## 4. wim-reconstruct Cloud Function deploy

**Effect:** signed-in WiM users with `profile_l1` set to any of the 10 languages now get pack-aware L2/L3 reconstruction server-side. Before this deploy, only russian/spanish/mandarin worked end-to-end on the signed-in path even after the source was committed.

- Source: `lavrentiy/wim/api/` directory (now with 10 packs in `l1_packs/`)
- Deploy: `gcloud functions deploy wim-reconstruct --source=lavrentiy/wim/api --gen2 --region=us-central1`
- New revision: `wim-reconstruct-00010-pej` ACTIVE
- URL unchanged: `us-central1-bakers-agent.cloudfunctions.net/wim-reconstruct`
- Existing env vars preserved (LOG_EXECUTION_ID, WIM_MODEL, WIM_MODEL_L4) and OPENAI_API_KEY secret reference

Sister Cloud Function (auto-detect L1 from text) `wim-l1-guess` also redeployed from `bakers-agent/wim-l1-guess-v1/` after `SUPPORTED_L1S` 3→10 + JSON-schema-string update. New revision `wim-l1-guess-00005-mox` ACTIVE. Public web demo at `gugosf114.github.io/l1-guesser/` now classifies across all 10 languages.

Smoke tests against the public `wim-l1-guess` endpoint:

| Sample | Predicted L1 | Confidence | Notes |
|---|---|---|---|
| Hindi-pattern (do the needful, am knowing, isn't it, good name, different-different) | hindi | 0.8 | 4 markers matched correctly |
| German-pattern (became a present, processing of the data, informations, dass-comma) | german | 0.6 | 3 markers; one with wrong-language marker_id citation but right language verdict |
| Japanese-pattern (went to airport, is breaking, These book, arrived the station, my father he is strict) | russian | 0.8 | **Mis-classified.** Japanese resultative `-te iru` + demonstrative-plural + locative drop overlap with Russian markers in the prompt context; classifier defaults to Russian. Real but non-blocking accuracy issue at the prompt-engineering layer; not a deploy fix. |

Disambiguation hint for the Cloud Function prompt is a future refinement — when patterns could fit multiple L1s, prefer the language with the most uniquely-identifying marker rather than the most overlapping marker.

---

## 5. Patent prior-art findings — Lav-relevant only

Operator ran a 3-pass cross-validation patent prior-art audit. Only the parts touching Lav-side mechanisms recapped here; the full thread + 3-way comparison + USPTO filing requirements + sharpened claim language live in WiM `SESSION_LOG_2026-04-30.md` (continued, evening).

Lav-relevant findings, manually verified at primary sources:

- **IBM US6006183 (Speech recognition confidence level display, 1997-12-16)** — verified **EXPIRED December 16, 2017** (20-year term ran out). For § 102 NOVELTY: still prior art (anticipates naked per-word confidence claims). For COMMERCIAL FREEDOM-TO-OPERATE: zero risk, no enforcement vector.

- **IBM US8620670 (Automatic realtime speech impairment correction, priority 2012-03-14)** — verified **LAPSED December 2025** for non-payment of maintenance fees. Audio-domain only — claim 1 requires "modify the audio signal by eliminating the identified audio signal artifacts." Distinguishable from Lav's text-domain LLM reconstruction. **The lapse opens text-domain stutter reconstruction territory entirely.** Significantly strengthens Lav's clinical-stutter framing for the foundation pitch.

- **US20250246187A1** (UC Regents, "Systems and methods for disfluent speech transcription and detection," filed Jan 31 2025) — verified REAL, PENDING. Different scope from Lav: claims AUDIO-domain disfluency detection via "recursive forced alignment" producing "two-dimensional alignment without monotonic alignment constraint" + "comparing pre-determined disfluency templates to the two-dimensional alignment." Lav does TEXT-domain LLM reconstruction post-ASR. Not anticipating, not gating. Cite in IDS at non-provisional.

---

## 6. State at end of session

- **Lavrentiy main**: clean, latest commit `2da039b` (operator-authored "Add L1 language marker packs and API copies"), pushed.
- **L1 packs live in 4 places**, MD5-byte-identical, all 10 languages.
- **wim-reconstruct deployed** (revision `wim-reconstruct-00010-pej` ACTIVE).
- **PhoneticMatcher gate**: L2/L3 only on Lav (matches WiM after parity port).
- **NATURAL_REPEATS list**: synced with WiM's 7 emphatic doublings.
- **`metaphone` PyPI dep**: in `Lavrentiy.spec` collect_all loop; bundled engines pre-this-change no-op gracefully.

---

## 7. Open / pending

1. **Voice end-to-end test of new L1 packs at L2** — record a Russian-L1, Hindi-L1, German-L1 phrase, observe normalization. Smoke-tested at the Cloud Function classifier level + at the helper-loader level, not yet at the dictation-pipeline level.

2. **Russian/Spanish/Mandarin marker packs are research-paper-curated, not community-curated.** Costanza-Chock framework upgrade (Pack Contribution Layer) discussed in WiM session log but deferred — not built. Architecture: opt-in user contribution of `(raw, model_output, user_correction)` triples to a Firestore collection; periodic LLM-assisted distillation of new markers; community-curator web surface for vote/edit. Estimated minimum-viable scope ~2 hours, full v1 ~1 week. Strengthens grant pitch from "academic-research-grounded equity infrastructure" to "first community-curated L1-transfer normalization platform."

3. **Native L1 picker UI in Lav dashboard** — currently must edit `~/.lavrentiy/profile.json` by hand. WiM Android has the Profile-screen dropdown; Lav does not. ~30 min addition to `dashboard.html` sidebar.

4. **Per-pattern toggle (normalize/preserve)** — designed in v2 plans, not yet built. Lets users opt to preserve specific markers as voice rather than normalize. Architecture supported by the existing pack JSON format; needs UI + pref-key + filter at injection time.

5. **Bilingual sniffer cross-port** — Lav has Cyrillic detector that injects "speaker is bilingual EN/RU" prompt note. WiM doesn't. Operator is bilingual EN/RU, so WiM-side absence is a real gap. ~10-line Kotlin port.

6. **Hallucination pattern + critical-token regex sync** — Lav has 47 patterns + longer regex; WiM has 42 + simpler regex. Sync direction Lav→WiM both edits.

7. **L2 cloud ASR fallback parity** — Lav uses `whisper-1`, WiM uses `gpt-4o-transcribe`. Pick one. Recommendation: WiM→Lav (use `whisper-1` at L2 too) preserves verbose_json reuse path, slightly slower than `gpt-4o-transcribe` but gives parity with L4.

---

## 8. Cross-references

- Patent prior-art 3-pass cross-validation, USPTO filing requirements, sharpened Claim 1 language, the two key research papers (Benjamin / Costanza-Chock), grant strategy, community-curation Pack Contribution Layer architecture proposal, adjacent-scholar reference list, and discoverability tactics for accent feature: see `wim-android/SESSION_LOG_2026-04-30.md` continued-evening section.

- Memory rules touched this session: `feedback_lav_wim_parity.md` (reinforced), `feedback_read_primary_before_characterizing.md` (applied during USPTO + patent verification), `feedback_verify_capability_before_punting.md` (applied after operator pushback on punting verification), `feedback_no_commit_push_without_check.md` (applied on bakers-agent surgical commit + WiM held for parallel-session safety).
