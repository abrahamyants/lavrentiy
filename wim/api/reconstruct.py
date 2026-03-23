"""
What I Meant — Reconstruction API
Standalone voice-to-intent reconstruction engine.
Extracted from Лаврентий (lavrentiy.py) for use as a GCP Cloud Function
or any HTTP endpoint.

Takes raw messy text + tone + profile → returns clean text + confidence score (γ).

Usage:
    from reconstruct import reconstruct_intent
    result = reconstruct_intent("so um like the thing is we need to uh get the report", tone="professional")
    # result = {"clean": "We need to get the report.", "confidence": 0.92, "ms": 340}

As Cloud Function:
    Deploy main.py which imports this module and exposes the HTTP handler.
"""

import json
import os
import re
import time

import openai

# ─── Config ───
MODEL = os.environ.get("WIM_MODEL", "gpt-4o-mini")
MODEL_L4 = os.environ.get("WIM_MODEL_L4", "gpt-4o-mini")
API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Try reading from api_key.txt (same dir as this file, or parent)
if not API_KEY:
    for p in [
        os.path.join(os.path.dirname(__file__), "api_key.txt"),
        os.path.join(os.path.dirname(__file__), "..", "..", "api_key.txt"),
    ]:
        if os.path.exists(p):
            API_KEY = open(p).read().strip()
            break

client = openai.OpenAI(api_key=API_KEY) if API_KEY else None

# ─── Bilingual filler set ───
_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}

# ─── Tone rules ───
TONE_RULES = {
    "formal": (
        "Use complete sentences. No contractions. No colloquialisms or slang. "
        "Proper grammar and punctuation. Do not paraphrase — preserve the speaker's "
        "exact word choices where possible. Only fix disfluencies and grammar errors."
    ),
    "professional": (
        "Clean, clear business language. Contractions acceptable but not preferred. "
        "Fix grammar and strip fillers. Minor rephrasing for clarity is OK, "
        "but do not editorialize or change the speaker's intent."
    ),
    "casual": (
        "Natural spoken rhythm. Contractions OK. Colloquial phrasing OK. "
        "Strip fillers and fix obvious errors, but keep the speaker's natural voice. "
        "Don't make it sound like a formal document."
    ),
    "friend": (
        "Conversational, relaxed. Contractions expected. Sentence fragments OK if natural. "
        "Strip fillers and repetitions but preserve personality and informal expressions. "
        "This should sound like a real person talking, not writing."
    ),
}

TONE_TEMP = {"formal": 0.1, "professional": 0.15, "casual": 0.35, "friend": 0.4}

# ─── Situation severity ───
SITUATION_SEVERITY = {"default": 1.0, "high_stress": 1.5, "reading": 0.5}


def strip_disfluencies(text):
    """Remove obvious disfluency artifacts from transcription (zero API cost)."""
    if not text or not text.strip():
        return text
    # Stutter fragments: "p- p- pop" → "pop"
    cleaned = re.sub(r'(\b\w+)-\s+(?:\1-\s+)*', '', text, flags=re.IGNORECASE)
    # Word repetitions: "I I I want" → "I want"
    cleaned = re.sub(r'\b(\w+)(?:\s+\1)+\b', r'\1', cleaned, flags=re.IGNORECASE)
    # Phrase repetitions: "I want I want to go" → "I want to go"
    cleaned = re.sub(r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', r'\1', cleaned, flags=re.IGNORECASE)
    # Strip filler words
    words = cleaned.split()
    filtered = []
    for w in words:
        w_lower = w.lower().rstrip('.,!?;:')
        if w_lower in _STRIP_FILLERS and len(words) > 1:
            continue
        filtered.append(w)
    result = " ".join(filtered).strip()
    result = re.sub(r'\s{2,}', ' ', result)
    return result if result else text


def build_prompt(raw_text, tone="casual", layer=2, profile=None, situation="default",
                 whisper_low_conf=None, whisper_disagreements=None,
                 speech_severity_mod=0.0):
    """Build the reconstruction system prompt. Pure function — no API calls."""
    profile = profile or {}
    tone_rule = TONE_RULES.get(tone, TONE_RULES["casual"])

    # Bilingual detection
    has_cyrillic = any('\u0400' <= c <= '\u04ff' for c in raw_text)
    lang_note = " Speaker is bilingual (English/Russian) and may mix languages." if has_cyrillic else ""

    # Situation severity
    severity = SITUATION_SEVERITY.get(situation, 1.0) + speech_severity_mod
    aggression_note = ""
    if severity >= 1.4:
        aggression_note = (
            " Speaker is in a HIGH-STRESS context. "
            "Expect more disfluencies, heavier avoidance, more filler stacking. "
            "Be MORE aggressive in reconstructing — strip more, trust less of the literal words."
        )
    elif severity >= 1.1:
        aggression_note = (
            " Speaker's speech shows elevated pausing or slow rate. "
            "Apply moderate cleanup — fix grammar, strip fillers, smooth hesitations."
        )
    elif severity <= 0.6:
        aggression_note = (
            " Speaker is in a low-stress context. Expect near-fluent speech. "
            "Be conservative — minor cleanup only."
        )

    parts = [
        f"Rebuild this raw voice transcription into clean {tone} text.{lang_note}{aggression_note}",
        tone_rule,
        "Strip filler words (including non-English fillers like э, ну, ээ).",
        "Preserve FULL meaning. Do not summarize or add information.",
        "Output ONLY the reconstructed text."
    ]

    # Filler list from profile
    if profile.get("filler_words"):
        parts.append(f"\nStrip these fillers: {', '.join(profile['filler_words'][:25])}")

    # L3+: vocabulary and corrections
    if layer >= 3 and profile:
        ctx = []
        if profile.get("vocabulary"):
            ctx.append(f"Preferred terms: {', '.join(profile['vocabulary'][:20])}")
        if profile.get("corrections"):
            pairs = [f"{k}->{v}" for k, v in list(profile["corrections"].items())[:10]]
            ctx.append(f"Known corrections: {'; '.join(pairs)}")
        if ctx:
            parts.append("\nUser context:\n" + "\n".join(ctx))

    # Whisper confidence signals
    if whisper_low_conf:
        lc_notes = []
        block_notes = []
        for seg in whisper_low_conf[:5]:
            if seg.get("block_suspect"):
                block_notes.append(f"  \"{seg['text']}\" (no_speech_prob={seg['no_speech_prob']})")
            else:
                lc_notes.append(
                    f"  \"{seg['text']}\" (logprob={seg['avg_logprob']}, brown_risk={seg.get('brown_risk', '?')})"
                )
        if lc_notes:
            if layer >= 4:
                parts.append(
                    "\n⚠ WHISPER UNCERTAINTY — these segments have low decoder confidence "
                    "AND high stuttering risk. They are almost certainly transcription artifacts:\n"
                    + "\n".join(lc_notes)
                    + "\nReconstruct aggressively. Trust semantic context, not the literal words."
                )
            else:
                parts.append(
                    "\n⚠ LOW CONFIDENCE — Whisper's decoder was uncertain about these words:\n"
                    + "\n".join(lc_notes)
                    + "\nThese may be misheard. Use surrounding context to determine what was actually said."
                )
        if block_notes:
            if layer >= 4:
                parts.append(
                    "\n⚠ BLOCK SUSPECTS — Whisper nearly classified these as silence "
                    "(high no_speech_prob). For this speaker, silence before/during a word "
                    "is a BLOCK, not absence of speech. The text here is likely hallucinated "
                    "filler that Whisper invented to fill the gap:\n"
                    + "\n".join(block_notes)
                    + "\nDiscard these words entirely or replace with the word the speaker "
                    "was trying to say (use semantic context from surrounding words)."
                )
            else:
                parts.append(
                    "\n⚠ POSSIBLE HALLUCINATION — Whisper nearly classified these segments as silence "
                    "but produced text anyway. The words here may be fabricated:\n"
                    + "\n".join(block_notes)
                    + "\nEvaluate carefully — if these words don't fit the context, discard them."
                )

    if whisper_disagreements:
        dis_notes = []
        for d in whisper_disagreements[:5]:
            variants = "/".join(set(d["variants"]))
            dis_notes.append(f"  position {d['position']}: [{variants}]")
        parts.append(
            "\n⚠ MULTI-PASS DISAGREEMENT — Whisper produced different words at these positions "
            "across 3 decoding temperatures. Disagreement = uncertain = likely misheard:\n"
            + "\n".join(dis_notes)
            + "\nThe truth is in the semantic context, not any single variant."
        )

    # L2/L3 general ASR artifact guidance
    if 2 <= layer <= 3:
        parts.append(
            "\nThe input is a voice transcription and may contain ASR artifacts:"
            "\n- Repeated words or phrases from natural speech hesitation"
            "\n- Filler sounds transcribed as real words (e.g., 'um' → 'come')"
            "\n- Phantom words inserted during pauses in speech"
            "\n- Phonetically similar but semantically wrong words (misheard)"
            "\n- Truncated or garbled words from unclear pronunciation"
            "\nWhen a word is phonetically plausible but doesn't fit the context, "
            "prefer the contextually correct interpretation."
            "\n\nExamples:"
            "\n  IN:  'So um I was going to uh the store to get some, some milk'"
            "\n  OUT: 'I was going to the store to get some milk'"
            "\n  IN:  'Can you send me the, the report by, by Friday'"
            "\n  OUT: 'Can you send me the report by Friday'"
        )

    # L4: Full clinical stutter context
    if layer >= 4:
        # Onset weights
        onset_weights = profile.get("onset_weights", {})
        if onset_weights:
            ranked = sorted(onset_weights.items(), key=lambda x: -x[1])
            hard = [f"/{o}/ ({round(w*100)}%)" for o, w in ranked[:6] if w >= 0.4]
            if hard:
                parts.append(
                    f"\n⚠ THIS SPEAKER'S HARDEST PHONEMES: {', '.join(hard)}"
                    "\nWhisper output near these onsets is unreliable — expect hallucinations, "
                    "syllable drops, or phantom word insertions. Trust semantic context."
                )

        # Covert avoidance pairs
        covert = profile.get("covert_profile", {}).get("avoidance_pairs", {})
        if covert:
            covert_note = []
            for sit, words in list(covert.items())[:3]:
                for word, data in list(words.items())[:3]:
                    subs = data.get("common_substitutes", [])[:2]
                    if subs:
                        covert_note.append(f"'{word}' → {subs}")
            if covert_note:
                parts.append(
                    "\n⚠ KNOWN COVERT AVOIDANCE: speaker sometimes swaps these words: "
                    + "; ".join(covert_note)
                    + "\nIf you see a synonym where the original word would fit better, "
                    "the original IS what they meant. Reconstruct with the intended word."
                )

        parts.append(
            "\nThe speaker stutters. Raw transcription is evidence, not truth. "
            "Reconstruct intended meaning, not literal word sequence."
            "\n\nOvert disfluencies — strip and reconstruct:"
            "\n- Part-word repetitions: 'b-b-b-buy' → 'buy'"
            "\n- Whole-word repetitions: 'I I I want' → 'I want'"
            "\n- Prolongations: 'mmmmaybe' → 'maybe'"
            "\n- Blocks: silence or frozen onset before a word"
            "\n- False starts and restarts"
            "\n\nCovert stuttering — recognize as avoidance, not content:"
            "\n- Filler clusters before a content word = delay tactic"
            "\n- Synonym substitution = avoiding a feared word"
            "\n- Circumlocution = talking around a feared word"
            "\n- Sentence abandonment = dropping thought before feared word"
            "\n\nWhisper ASR failure modes on stuttered speech:"
            "\n- HALLUCINATION DURING BLOCKS: silence → Whisper invents words"
            "\n- SYLLABLE DELETION: repeated syllables get collapsed"
            "\n- PHANTOM INSERTIONS: during prolongations, Whisper hallucinates"
            "\n- SCHWA CORRUPTION: neutral vowel transcribed as real word"
            "\n\nDo not mistake disfluency for emphasis. "
            "When uncertain, prefer conservative cleanup over aggressive rewriting."
        )

        if profile.get("trigger_words"):
            parts.append(f"\nKnown trigger words: {', '.join(profile['trigger_words'])}")

    return "\n".join(parts)


def falcon_validate(raw_text, clean_text, layer=2):
    """Binary meaning check. Returns True if meaning preserved."""
    if layer >= 4:
        prompt = (
            "Speaker stutters. Repeated syllables, prolongations, and blocks are "
            "disfluencies, not emphasis. Filler clusters are postponement tactics. "
            "Synonym substitutions are avoidance behaviors — the reconstruction should "
            "recover the intended word. Does the reconstruction preserve intended meaning? "
            "Answer ONLY 'yes' or 'no'."
        )
    else:
        prompt = (
            "The reconstruction cleans up a voice transcription: removing filler words, "
            "fixing grammar, and improving clarity. Filler removal and grammar fixes are "
            "expected. Does the reconstruction preserve the core content and intent? "
            "Answer ONLY 'yes' or 'no'."
        )

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Original: {raw_text}\nReconstruction: {clean_text}"}
        ],
        max_tokens=5,
        temperature=0
    )
    return "yes" in resp.choices[0].message.content.strip().lower()


def compute_confidence(raw_text, clean_text, falcon_ok, layer=2):
    """Compute intent confidence score (γ) between 0 and 1.

    Factors:
    - Falcon validation (binary meaning check)
    - Length ratio (extreme compression = lower confidence)
    - Layer (higher layers = more aggressive reconstruction = needs more trust)
    """
    if not falcon_ok:
        return 0.3  # Falcon rejected — low confidence

    raw_words = len(raw_text.split())
    clean_words = len(clean_text.split())

    if raw_words == 0:
        return 0.5

    ratio = clean_words / raw_words

    # Base confidence from Falcon pass
    gamma = 0.85

    # Penalize extreme compression (output is <30% of input)
    if ratio < 0.3:
        gamma -= 0.15
    # Penalize extreme expansion (output is >150% of input — hallucination risk)
    elif ratio > 1.5:
        gamma -= 0.2

    # Higher layers = more aggressive reconstruction = slightly lower base confidence
    if layer >= 4:
        gamma -= 0.05

    # Very short input = less context = lower confidence
    if raw_words < 4:
        gamma -= 0.1

    return round(max(0.1, min(1.0, gamma)), 2)


def reconstruct_intent(raw_text, tone="casual", layer=2, profile=None,
                       situation="default", mode="FAST",
                       whisper_low_conf=None, whisper_disagreements=None,
                       speech_severity_mod=0.0):
    """Main entry point. Takes raw messy text, returns clean text + confidence.

    Args:
        raw_text: Raw transcription from Whisper or device ASR.
        tone: One of "formal", "professional", "casual", "friend".
        layer: 1=transcribe only, 2=reconstruct, 3=+profile, 4=+stutter.
        profile: Dict with vocabulary, corrections, filler_words, trigger_words, etc.
        situation: "default", "high_stress", or "reading".
        mode: "RAW" (no processing), "FAST" (skip Falcon), "SAFE" (full pipeline).
        whisper_low_conf: Low-confidence segments from Whisper.
        whisper_disagreements: Multi-temp disagreements from Whisper.
        speech_severity_mod: Dynamic severity boost from speech rate analysis.

    Returns:
        dict with: clean, raw, confidence, falcon_ok, ms, mode, tone, layer
    """
    if not client:
        return {"error": "No API key configured", "raw": raw_text, "clean": raw_text,
                "confidence": 0.0, "ms": 0}

    t0 = time.time()
    profile = profile or {}

    # L1: disfluency strip only, no API call
    if layer <= 1 or mode == "RAW":
        cleaned = strip_disfluencies(raw_text)
        ms = round((time.time() - t0) * 1000)
        return {
            "clean": cleaned, "raw": raw_text, "confidence": 0.95,
            "falcon_ok": True, "ms": ms, "mode": mode, "tone": tone, "layer": layer
        }

    # L2+: build prompt and call GPT
    system_prompt = build_prompt(
        raw_text, tone=tone, layer=layer, profile=profile, situation=situation,
        whisper_low_conf=whisper_low_conf, whisper_disagreements=whisper_disagreements,
        speech_severity_mod=speech_severity_mod
    )

    temp = TONE_TEMP.get(tone, 0.3)
    use_model = MODEL_L4 if layer >= 4 else MODEL

    resp = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text}
        ],
        max_tokens=1000,
        temperature=temp
    )
    clean_text = resp.choices[0].message.content.strip()

    # Falcon validation (SAFE mode only)
    falcon_ok = True
    if mode == "SAFE":
        falcon_ok = falcon_validate(raw_text, clean_text, layer)
        if not falcon_ok:
            clean_text = strip_disfluencies(raw_text)

    # Confidence score (γ)
    gamma = compute_confidence(raw_text, clean_text, falcon_ok, layer)

    ms = round((time.time() - t0) * 1000)

    return {
        "clean": clean_text,
        "raw": raw_text,
        "confidence": gamma,
        "falcon_ok": falcon_ok,
        "ms": ms,
        "mode": mode,
        "tone": tone,
        "layer": layer,
    }
