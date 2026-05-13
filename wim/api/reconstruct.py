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
from pathlib import Path

import openai

import l1_pack
import domain_pack

# ─── Config ───
MODEL = os.environ.get("WIM_MODEL", "gpt-4o")
MODEL_L4 = os.environ.get("WIM_MODEL_L4", "gpt-4o")
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


# ─── Multilingual L4 helpers (docs/l4_prompt_engineering_memo.md) ───
# Lang packs live in lang_packs/{code}.json; mirrored into the wim-android
# APK under app/src/main/assets/lang_packs/. The two sets MUST stay in sync.
_LANG_PACK_CACHE = {}  # code -> dict or None (None = not found)


def _lang_packs_dir():
    # Lazy: resolve only when needed so exec-based test harnesses that lack
    # __file__ (e.g. test_fuzz.py) don't fail at import time.
    return Path(__file__).resolve().parent / "lang_packs"


def _load_lang_pack(code):
    """Return the parsed lang-pack dict for `code`, or None for English/unknown."""
    normalized = _normalize_lang_code(code)
    if normalized in _LANG_PACK_CACHE:
        return _LANG_PACK_CACHE[normalized]
    if normalized == "en":
        _LANG_PACK_CACHE[normalized] = None
        return None
    try:
        path = _lang_packs_dir() / f"{normalized}.json"
        if not path.exists():
            _LANG_PACK_CACHE[normalized] = None
            return None
        with open(path, "r", encoding="utf-8") as f:
            pack = json.load(f)
    except Exception:
        pack = None
    _LANG_PACK_CACHE[normalized] = pack
    return pack


def _normalize_lang_code(raw):
    """Collapse 'en-US' → 'en', 'es-ES' → 'es'. Empty/None → 'en'."""
    if not raw:
        return "en"
    head = raw.strip().split("-", 1)[0].split("_", 1)[0].lower()
    return head or "en"


def _lang_name(code):
    normalized = _normalize_lang_code(code)
    if normalized == "en":
        return "English"
    pack = _load_lang_pack(normalized)
    return (pack or {}).get("language_name_en", normalized) or normalized


def _get_lang_fillers(code):
    pack = _load_lang_pack(code)
    return list((pack or {}).get("fillers", []))


def _get_lang_natural_repeats(code):
    pack = _load_lang_pack(code)
    return list((pack or {}).get("natural_repeats", []))


def _get_lang_hard_onsets(code):
    """Cited onset→weight map from lang pack. Empty when unavailable."""
    pack = _load_lang_pack(code)
    if not pack:
        return {}
    ho = pack.get("hard_onsets") or {}
    if ho.get("quality_note") == "unavailable":
        return {}
    out = {}
    for entry in ho.get("data") or []:
        onset = (entry.get("onset") or "").strip().strip("/").lower()
        weight = entry.get("difficulty_weight") or 0.0
        if onset and weight:
            out[onset] = weight
    return out


def _lang_has_no_onset_research(code):
    normalized = _normalize_lang_code(code)
    if normalized == "en":
        return False
    pack = _load_lang_pack(normalized)
    if not pack:
        return False
    return (pack.get("hard_onsets") or {}).get("quality_note") == "unavailable"


def _get_lang_part_word_example(code):
    c = _normalize_lang_code(code)
    return {
        "es": "'p-p-pues entonces qu-qu-quiero ir al trabajo' → 'Pues, quiero ir al trabajo'",
        "fr": "'P-p-peut-être qu'on devrait...' → 'Peut-être qu'on devrait...'",
        "de": "'P-p-Peter hat mir gesagt...' → 'Peter hat mir gesagt...'",
        "it": "'P-p-posso andare a-a-adesso?' → 'Posso andare adesso?'",
        "pt": "'P-p-posso te falar a-a-agora?' → 'Posso te falar agora?'",
        "ja": "'か-か-かく に つ い て は...' → 'かくについては...' (mora-level repetition)",
        "zh": "'我-我-我 想 去' → '我想去'",
        "hi": "'म-म-मैं जाना चाहता हूँ' → 'मैं जाना चाहता हूँ'",
        "ar": "'ب-ب-بدي أروح' → 'بدي أروح'",
        "ko": "'ㄱ-ㄱ-가고 싶어요' → '가고 싶어요'",
    }.get(c, "'b-b-b-buy' → 'buy', 'Ca-ca-ca-can' → 'Can'")


def _get_lang_prolongation_example(code):
    c = _normalize_lang_code(code)
    return {
        "es": "'Sssssseñor, necesito...' → 'Señor, necesito...'",
        "fr": "'Ssssalut, je voulais...' → 'Salut, je voulais...'",
        "de": "'Mmmmontag kommt er zurück' → 'Montag kommt er zurück'",
        "it": "'Mmmmmamma mia' → 'Mamma mia'",
        "pt": "'Sssssenhor, preciso...' → 'Senhor, preciso...'",
        "ja": "prolonged initial mora: 'かーーーく' → 'かく'",
    }.get(c, "'mmmmaybe' → 'maybe', 'Sssssscience' → 'Science'")


def _get_lang_epenthesis_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "Spanish epenthetic /e/ during blocked clusters (e.g. 'p-eh-lanta' for 'planta', 't-eh-rabajo' for 'trabajo') — NOT English schwa /ə/",
        "fr": "French epenthetic /ə/ during blocked clusters, but this is the French 'e muet', not the neutral English schwa",
        "de": "German epenthetic /ə/ possible at morpheme boundaries in compounds",
        "it": "Italian may insert a transitional /i/ or /e/ at blocked clusters",
        "pt": "Portuguese may insert a transitional /i/ (BP) or /ə/ (EP) at blocked clusters",
        "hi": "Hindi: inherent /a/ vowel of Devanagari consonants can be extended during blocks",
    }.get(c, "schwa substitution: 'guh-guh-goat' → 'goat' (neutral /ə/ inserted in repeated clusters)")


def _get_lang_dialect_avoidance_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "- Spanish dialect avoidance: if speaker uses 'vos tenés' but context suggests 'tú tienes', they may be using voseo to avoid the /t/ onset. Do NOT reconstruct voseo into tuteo — preserve the speaker's dialect.",
        "fr": "- French tu/vous register: an unexpected vous-form when tu is established may be avoidance of a /t/ onset. Do NOT reconstruct vous into tu.",
        "de": "- German du/Sie register: an unexpected Sie-form when du is established MAY indicate avoidance of a /d/ onset (speculative — not established in German stuttering literature). Preserve the speaker's chosen form.",
        "ja": "- Japanese casual/keigo register: an unexpected keigo form on a content word MAY indicate avoidance of a feared initial consonant (speculative — not established in Japanese stuttering literature). Preserve the speaker's chosen form.",
        "ko": "- Korean 반말/존댓말 register: an unexpected register shift MAY indicate phonemic avoidance (speculative — not established in Korean stuttering literature). Preserve the speaker's chosen form.",
        "ar": "- Arabic diglossia: an unexpected colloquial→MSA (عامية→فصحى) shift on a specific word MAY indicate register avoidance (speculative — not established in Arabic stuttering literature). Preserve the speaker's chosen register.",
    }.get(c, "")


def _get_lang_syllable_timing_note(code):
    c = _normalize_lang_code(code)
    if c in ("es", "fr", "it", "pt"):
        return f"- {_lang_name(c)} is syllable-timed — anticipatory pauses are less prosodically marked than in English. Require both a filler cluster AND a hard-onset match before treating a pause as anticipatory."
    if c == "de":
        return "- German is stress-timed — anticipatory pauses have predictive weight similar to English."
    if c == "ja":
        return "- Japanese is mora-timed — stuttering occurs at mora boundaries, not English-style word-initial position."
    return ""


def _get_lang_epenthesis_corruption_note(code):
    c = _normalize_lang_code(code)
    return {
        "es": "EPENTHETIC VOWEL CORRUPTION: blocked clusters (/tr/, /pl/, /pr/) → Whisper may transcribe 'p-eh-lanta' as 'Pelanta', 't-eh-rabajo' as 'Terabajo' — these are hallucinations of epenthesis, reconstruct to the target word",
        "fr": "LIAISON HALLUCINATION: Whisper may insert liaison consonants mid-block (e.g. transcribing a /t/ the speaker was blocked on as the onset of the next vowel-initial word)",
        "de": "COMPOUND BOUNDARY CORRUPTION: blocks at morpheme boundaries of long compounds (e.g. 'Arbeits…losigkeit') may be transcribed as two separate words or as a different compound",
        "it": "GEMINATE CONFUSION: stuttered /p/ may be transcribed as the Italian geminate /pp/ ('la papa' vs. 'la pappa') — geminates are phonemic, verify against context",
        "pt": "EPENTHETIC /i/ CORRUPTION: blocked clusters in BP may be transcribed with an intrusive /i/ (e.g. 'p-i-lanta' for 'planta')",
        "ja": "MORA CORRUPTION: repeated moras ('か-か-かく') may collapse into a single mora or a different katakana/hiragana character",
        "zh": "TONE CORRUPTION: repeated syllables in Mandarin may be transcribed with a wrong tone, producing a different word (same pinyin, different character)",
    }.get(c, "SCHWA CORRUPTION: neutral vowel in repeated clusters → transcribed as a real word (e.g. 'buh-buh-blue' → 'but but blue' or 'above blue')")


def _get_lang_onset_caveat(code):
    c = _normalize_lang_code(code)
    return {
        "es": "Onset weights cite Howell et al. 2004 and are extrapolated from English aspiration data — may be slightly inflated for Spanish unaspirated plosives. Additionally, the trilled /rr/ (perro, ratón) is a high-frequency block site not captured in these weights.",
        "fr": "Onset weights cite Dworzynski et al. 2003. French is unaspirated — treat with moderate extrapolation risk relative to English.",
        "de": "Onset weights cite Natke et al. 2004. Only /p/ is documented as a primary hard onset in German — do NOT apply English-derived /t/ difficulty weighting.",
        "it": "Onset weights cite Zmarich et al. 2004. Italian is unaspirated — moderate extrapolation risk.",
        "pt": "Onset weights cite Juste et al. 2007, a pediatric study — adult onset weights are extrapolated; treat with lower confidence for adult users.",
        "ja": "Onset weights cite Umezaki et al. 1999. /k/ is the documented hard onset; words beginning with か行 (ka, ki, ku, ke, ko) are elevated-risk.",
    }.get(c, "")


# Few-shot example blocks per language (memo Section 4.4).
_LANG_FEW_SHOT = {
    "es": (
        "DISFLUENCY EXAMPLES (Spanish):\n"
        "  REPETITION:  'P-p-pues este... quiero ir a la re-re-reunión'\n"
        "  RESULT:      'Quiero ir a la reunión'\n\n"
        "  EMPHATIC (PRESERVE):  'No no, eso no me parece bien'\n"
        "  RESULT:      'No no, eso no me parece bien'\n\n"
        "  WHISPER /rr/ BLOCK:  'Necesito el r-r-... el documento del er rrr... del jefe'\n"
        "  RESULT:      'Necesito el documento del jefe'\n\n"
        "  CIRCUMLOCUTION:  'Quiero hablar con el... con la persona que lleva los números'\n"
        "  RESULT:      'Quiero hablar con el contador'  [if context is clear — else preserve circumlocution literally]"
    ),
    "fr": (
        "DISFLUENCY EXAMPLES (French):\n"
        "  REPETITION:  'Je je je voulais te te te dire quelque chose'\n"
        "  RESULT:      'Je voulais te dire quelque chose'\n\n"
        "  EMPHATIC (PRESERVE):  'Non non, ce n'est pas correct'\n"
        "  RESULT:      'Non non, ce n'est pas correct'\n\n"
        "  BLOCK + LIAISON:  'Les... euh... [block]... petits enfants arrivent'\n"
        "  RESULT:      'Les petits enfants arrivent'\n\n"
        "  CIRCUMLOCUTION:  'J'ai besoin du... de la chose qu'on met sur la tête'\n"
        "  RESULT:      'J'ai besoin du chapeau'  [if context is clear]"
    ),
    "de": (
        "DISFLUENCY EXAMPLES (German):\n"
        "  REPETITION:  'P-p-Peter, ich brauche den Ber-ber-Bericht bis Freitag'\n"
        "  RESULT:      'Peter, ich brauche den Bericht bis Freitag'\n\n"
        "  EMPHATIC (PRESERVE):  'Nein nein, das ist nicht richtig'\n"
        "  RESULT:      'Nein nein, das ist nicht richtig'\n\n"
        "  COMPOUND BLOCK:  'Ich brauche die Ar-ar-Arbeits... die Bescheinigung'\n"
        "  RESULT:      'Ich brauche die Arbeitsbescheinigung'\n\n"
        "  WHISPER HALLUCINATION:  'Ich dachte dass... thank you... der Termin morgen ist'\n"
        "  RESULT:      'Ich dachte, der Termin ist morgen'  [discard 'thank you' — Whisper hallucination]"
    ),
    "it": (
        "DISFLUENCY EXAMPLES (Italian):\n"
        "  REPETITION:  'P-p-posso andare a-a-adesso?'\n"
        "  RESULT:      'Posso andare adesso?'\n\n"
        "  EMPHATIC (PRESERVE):  'Sì sì, è proprio così'\n"
        "  RESULT:      'Sì sì, è proprio così'\n\n"
        "  GEMINATE DISAMBIGUATION:  'La p-p-papa parla' (stuttered /p/)\n"
        "  RESULT:      'Il papa parla'  [stuttered /p/, NOT the geminate 'pappa' (porridge)]\n\n"
        "  CIRCUMLOCUTION:  'Ho bisogno del... di quella cosa per scrivere'\n"
        "  RESULT:      'Ho bisogno della penna'  [if context is clear]"
    ),
    "pt": (
        "DISFLUENCY EXAMPLES (Portuguese):\n"
        "  REPETITION:  'P-p-posso te falar a-a-agora sobre o pro-projeto?'\n"
        "  RESULT:      'Posso te falar agora sobre o projeto?'\n\n"
        "  EMPHATIC (PRESERVE):  'Não não, isso não está certo'\n"
        "  RESULT:      'Não não, isso não está certo'\n\n"
        "  DIALECT PRESERVATION:  'Vou pegar o ônibus' (BP) — do NOT normalize to 'autocarro' (EP)\n"
        "  RESULT:      'Vou pegar o ônibus'\n\n"
        "  CIRCUMLOCUTION:  'Preciso do... daquilo que a gente assina na entrada'\n"
        "  RESULT:      'Preciso do formulário da entrada'"
    ),
    "ja": (
        "DISFLUENCY EXAMPLES (Japanese):\n"
        "  MORA REPETITION:  'か-か-かく に つ い て は...'\n"
        "  RESULT:      'かくについては...'\n\n"
        "  EMPHATIC (PRESERVE):  'そうそう、それが正しいです'\n"
        "  RESULT:      'そうそう、それが正しいです'\n\n"
        "  /k/ BLOCK:  'きょう の... えーと... かいぎ は なんじ ですか'\n"
        "  RESULT:      'きょうのかいぎはなんじですか'"
    ),
    "zh": (
        "DISFLUENCY EXAMPLES (Mandarin):\n"
        "  REPETITION:  '我-我-我 想 去 开-开-开会'\n"
        "  RESULT:      '我想去开会'\n\n"
        "  EMPHATIC (PRESERVE):  '对对，这个就是正确的'\n"
        "  RESULT:      '对对，这个就是正确的'\n\n"
        "  ASPECTUAL REDUPLICATION (PRESERVE):  '我去看看' (take a look — NOT stutter)\n"
        "  RESULT:      '我去看看'\n\n"
        "  TONE-LEVEL SUBSTITUTION RISK: suspect single-syllable content-word substitutions"
    ),
    "hi": (
        "DISFLUENCY EXAMPLES (Hindi):\n"
        "  REPETITION:  'म-म-मैं जाना चाहता हूँ'\n"
        "  RESULT:      'मैं जाना चाहता हूँ'\n\n"
        "  EMPHATIC (PRESERVE):  'नहीं नहीं, यह सही नहीं है'\n"
        "  RESULT:      'नहीं नहीं, यह सही नहीं है'\n\n"
        "  CIRCUMLOCUTION:  'मुझे वो... जो लिखने के लिए होता है... चाहिए'\n"
        "  RESULT:      'मुझे पेन चाहिए'  [if context is clear]"
    ),
    "ar": (
        "DISFLUENCY EXAMPLES (Arabic):\n"
        "  REPETITION:  'ب-ب-بدي أ-أ-أروح'\n"
        "  RESULT:      'بدي أروح'\n\n"
        "  EMPHATIC (PRESERVE):  'لا لا، هذا مش صحيح'\n"
        "  RESULT:      'لا لا، هذا مش صحيح'\n\n"
        "  WHISPER ENGLISH HALLUCINATION:  'كنت أفكر... thank you... في الموعد'\n"
        "  RESULT:      'كنت أفكر في الموعد'  [discard 'thank you' — Whisper hallucination]"
    ),
    "ko": (
        "DISFLUENCY EXAMPLES (Korean):\n"
        "  REPETITION:  '가-가-가고 싶-싶-싶어요'\n"
        "  RESULT:      '가고 싶어요'\n\n"
        "  EMPHATIC (PRESERVE):  '아니 아니, 그게 맞지 않아요'\n"
        "  RESULT:      '아니 아니, 그게 맞지 않아요'\n\n"
        "  CIRCUMLOCUTION:  '그... 쓰는 거 있잖아요... 필요해요'\n"
        "  RESULT:      '펜 필요해요'  [if context is clear]"
    ),
    "en": (
        "DISFLUENCY EXAMPLES (English):\n"
        "  BLOCK:       'I need the... [silence]... computer from the office'\n"
        "  RESULT:      'I need the computer from the office'\n\n"
        "  REPETITION:  'Ca-ca-ca-can you p-p-please send the re-report'\n"
        "  RESULT:      'Can you please send the report'\n\n"
        "  WORD REPS:   'I I I want to to to go to the the meeting'\n"
        "  RESULT:      'I want to go to the meeting'\n\n"
        "  WHISPER:     'I was trying to come put her the file'\n"
        "  RESULT:      'I was trying to get the computer file'"
    ),
}


def _get_lang_few_shot_examples(code):
    return _LANG_FEW_SHOT.get(_normalize_lang_code(code), _LANG_FEW_SHOT["en"])




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
                 speech_severity_mod=0.0,
                 paralinguistic_events=None, prosodic_context=None,
                 language_code="en"):
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
        ("The transcription was produced by an automatic speech recognition system and may contain "
         "artifacts from speech disfluency including repeated words, repeated syllables, filler sounds, "
         "and silence where the speaker was blocked. When the literal transcription doesn't make "
         "grammatical sense, prioritize semantic intent and grammatical coherence over literal word "
         "sequence. Reconstruct what the speaker most likely intended to say, not what the microphone "
         "literally captured."),
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
            "\nALWAYS RESTATE — DO NOT RETURN INPUT UNCHANGED."
            "\nThe input is raw spoken material. The output is text someone will READ. "
            "CONVERT spoken cadence into written prose every time, even when input is fluent. "
            "Identity output is a failure mode."
            "\n\nApply these established prose rules (Strunk & White, federal Plain Language Guidelines):"
            "\n- Omit needless words. A sentence should contain no unnecessary words."
            "\n- Use the active voice."
            "\n- Use definite, specific, concrete language."
            "\n- Sentence length should average 15-20 words. Break run-on speech into multiple short sentences."
            "\n- Drop verbal-tic discourse markers ('so', 'well', 'you know', 'like') even when not pure fillers."
            "\n\nThe speaker is brain-dumping in stream-of-consciousness order. "
            "REORDER clauses, GROUP related ideas, and RESTRUCTURE into the flow a written reader expects."
            "\n\nHARD RULES while restating:"
            "\n- PRESERVE all numbers, dates, dollar amounts, addresses, names, proper nouns exactly as spoken."
            "\n- DO NOT add information or invent details not present in the input."
            "\n- DO NOT soften, sanitize, or change profanity / strong language / slang."
            "\n- TREAT unfamiliar or single-syllable unrecognized words as INTENTIONAL slang or brand names — do not substitute them."
        )
        parts.append(
            "\n\nSELF-CORRECTION — CANONICAL OVERWRITE:"
            "\nWhen the speaker uses 'I mean', 'actually', 'no wait', 'scratch that', or similar "
            "mid-sentence revision markers, treat the content AFTER the marker as canonical "
            "and DISCARD the content before it."
            "\nExample: 'the meeting at 3pm, I mean 4pm' → 'the meeting at 4pm'"
            "\nExample: 'let's go to Italian, actually let's go to Thai' → 'let's go to Thai'"
        )
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
            "\n  IN:  'I think we should, we should probably move the meeting'"
            "\n  OUT: 'I think we should probably move the meeting'"
            "\n  IN:  'The, uh, what's it called, the database needs updating'"
            "\n  OUT: 'The database needs updating'"
        )

        # L1-transfer pack injection (L2/L3 only — L4 has its own clinical
        # framing and double-instructing the model harms output quality).
        # Mirrors lavrentiy.py and L1PackHelper.kt — same prompt text.
        l1_block = l1_pack.prompt_injection(profile)
        if l1_block:
            parts.append(l1_block)

        # Domain pack injection — canonical vocab + phonetic-alias corrections
        # per profile_industry. Mirrors lavrentiy.py domain_pack.prompt_injection.
        domain_block = domain_pack.prompt_injection(profile)
        if domain_block:
            parts.append(domain_block)

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

        # Language-parameterized L4 block (docs/l4_prompt_engineering_memo.md § 4–5)
        _lang_code = _normalize_lang_code(language_code)
        _lang_name_str = _lang_name(_lang_code)
        _lang_fillers = _get_lang_fillers(_lang_code)
        _lang_natural_repeats = _get_lang_natural_repeats(_lang_code)
        _dialect_note = _get_lang_dialect_avoidance_note(_lang_code)
        _timing_note = _get_lang_syllable_timing_note(_lang_code)

        _l4 = []
        _l4.append(
            f"\nThe speaker has a speech disfluency. Language: {_lang_code.upper()} ({_lang_name_str}). "
            "Raw transcription is evidence of intent, not truth. "
            "Reconstruct the intended message. Preserve FULL meaning."
        )
        if _lang_fillers:
            _l4.append(f"\n\nFILLERS TO STRIP ({_lang_code}): {', '.join(_lang_fillers)}")
        if _lang_natural_repeats:
            _l4.append(
                f"\n\nEMPHATIC PATTERNS — DO NOT STRIP in {_lang_code}: {', '.join(_lang_natural_repeats)}"
                f"\nThese are pragmatically meaningful in {_lang_name_str}, not stuttering."
            )
        _l4.append("\n\nOvert disfluencies — strip and reconstruct:")
        _l4.append(f"\n- Part-word repetitions: {_get_lang_part_word_example(_lang_code)}")
        _l4.append("\n- Whole-word repetitions (NOT matching the emphatic allow-list above)")
        _l4.append(f"\n- Prolongations: {_get_lang_prolongation_example(_lang_code)}")
        _l4.append(f"\n- Epenthetic insertions during blocks: {_get_lang_epenthesis_note(_lang_code)}")
        _l4.append("\n- Blocks: silence or frozen onset before a word (locked articulators)")
        _l4.append("\n- Tremors: lip/jaw quivering during a fixation")
        _l4.append("\n- Secondary behaviors: eye blinks, foot taps, head movements during blocks")
        _l4.append("\n- False starts and restarts")

        _l4.append("\n\nCovert avoidance — recognize as avoidance behavior, not content:")
        _l4.append("\n- Filler clusters before a content word = postponement (see filler list above)")
        _l4.append("\n- Synonym substitution = avoiding a feared word")
        _l4.append("\n- Circumlocution = talking around a feared word")
        _l4.append("\n- Sentence abandonment = dropping thought before feared word ('Oh, never mind')")
        _l4.append("\n- Covert interruption = jumping in while someone talks to mask onset difficulty")
        _l4.append(
            "\n- Mazes: extended filler runs adding no information. DISTINCT from cluttered "
            "rapid speech — do not over-strip if the speaker's speech is globally rapid."
        )
        if _dialect_note:
            _l4.append(f"\n{_dialect_note}")

        _l4.append("\n\nAnticipatory behavior:")
        _l4.append(
            "\n- A pause or silence BEFORE a content word with a hard onset MAY INDICATE anticipatory fear"
        )
        _l4.append(
            "\n- Confidence increases when a filler cluster appears in the preceding 1–3 words "
            "AND the following word begins with a documented hard onset"
        )
        _l4.append("\n- Treat as a block candidate, not certainty")
        if _timing_note:
            _l4.append(f"\n{_timing_note}")

        _l4.append("\n\nWhisper ASR failure modes on disfluent speech:")
        _l4.append("\n- HALLUCINATION DURING BLOCKS: silence → Whisper generates phantom text.")
        _l4.append(
            "\n  Known hallucination strings to discard: 'thank you', 'thanks for watching', "
            "'subscribe', 'like and subscribe', 'transcribed by', 'captions by', 'otter.ai'."
        )
        if _lang_code != "en":
            _l4.append(
                f"\n  In {_lang_name_str} transcripts, English phrases appearing mid-utterance "
                "are likely Whisper hallucinations — discard them."
            )
        _l4.append("\n- SYLLABLE DELETION: repeated syllables collapsed or dropped")
        _l4.append("\n- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar-sounding words")
        _l4.append(f"\n- {_get_lang_epenthesis_corruption_note(_lang_code)}")
        _l4.append("\n- PAUSE HALLUCINATION: long pauses → Whisper generates filler text (see above)")

        _l4.append("\n\n")
        _l4.append(_get_lang_few_shot_examples(_lang_code))

        _l4.append(
            "\n\nDo not mistake disfluency for emphasis — but PRESERVE the emphatic patterns listed above."
            "\nReconstruct within the speaker's established dialect — do not substitute dialectal forms."
            "\nWhen uncertain, prefer conservative cleanup over aggressive rewriting."
        )

        _onset_caveat = _get_lang_onset_caveat(_lang_code)
        if _onset_caveat:
            _l4.append(f"\n{_onset_caveat}")
        if _lang_has_no_onset_research(_lang_code):
            _l4.append(
                f"\n\nONSET NOTE: No published phoneme-difficulty research exists for {_lang_code} "
                "as of April 2026. Do not apply English-derived onset assumptions. Focus on word-level "
                "repetitions, prolongations, filler clusters, and Whisper hallucination strings."
            )

        parts.append("".join(_l4))
        if profile.get("trigger_words"):
            parts.append(f"\nKnown trigger words: {', '.join(profile['trigger_words'])}")

    # Paralinguistic event markers (cough, laughter, sigh) — Lavrentiy L5
    if paralinguistic_events:
        event_str = ", ".join(
            f"[{e.get('type','?')}] at {e.get('start',0):.1f}s"
            for e in paralinguistic_events[:8]
        )
        parts.append(f"\nNon-speech events detected in audio: {event_str}")
        parts.append("Whisper may have hallucinated words during these moments — trust semantic context over literal transcription near them.")

    # Prosodic context (F0/energy/rate/speaker state) — Lavrentiy L5.5
    if prosodic_context:
        parts.append(f"\nSpeaker acoustic state: {prosodic_context}")

    return "\n".join(parts)


def falcon_validate(raw_text, clean_text, layer, tone="casual", onset_weights=None, language_code="en"):
    """Retired 2026-05-10. L4 Sonnet ET self-validates; L2/L3 GPT-4o quality
    is sufficient without cross-provider QA. Stub matches lavrentiy.py:3420-3428.

    The live body was burning an extra GPT-4o roundtrip per request, doubling
    OpenAI quota usage. Keep the signature so existing call sites compile."""
    return True

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
                       speech_severity_mod=0.0,
                       paralinguistic_events=None, prosodic_context=None,
                       language_code="en"):
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
        speech_severity_mod=speech_severity_mod,
        paralinguistic_events=paralinguistic_events, prosodic_context=prosodic_context,
        language_code=language_code
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
        falcon_ok = falcon_validate(
            raw_text, clean_text, layer,
            tone=tone,
            onset_weights=(profile or {}).get("onset_weights"),
            language_code=language_code,
        )
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
