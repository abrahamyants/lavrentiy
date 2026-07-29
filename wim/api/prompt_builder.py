"""
Unified L1/L2/L3/L4 prompt builder — single source of truth.

Imported by both:
  - lavrentiy.py::reconstruct() (desktop engine)
  - wim/api/reconstruct.py::build_prompt() / reconstruct_intent() (Cloud Function)

Previously each had its own copy of the prompt assembly logic, which drifted —
WiM CF had dropped the anti-censoring rule, no-markdown rule, single-line rule,
"let me rephrase" self-correction marker, 3 Strunk & White bullets, 2 hard rules,
and the rich examples in tone severity blocks. This module is the canonical
version.

Imports `l1_pack` and `domain_pack` as bare names — both are present at the CF
deploy root (wim/api/) and at lavrentiy's repo root, and Python's module cache
keeps the two callers seeing the same modules they would have seen pre-refactor.
"""

import json
import re
from pathlib import Path

import l1_pack
import domain_pack


# ─── Audience-context window-title map (ported from AudienceContext.kt) ───
# Each entry: (title_keyword_lowercase, category, audience, medium_expectations)
_WINDOW_AUDIENCE = [
    ("com.microsoft.office.outlook", "email", "professional contacts",       "full sentences, formal tone, clear subject-action structure"),
    ("com.google.android.gm", "email", "professional or personal contacts", "full sentences, structured paragraphs"),
    ("com.slack",  "team chat",  "colleagues or project peers",             "short, casual, no sign-offs"),
    ("com.whatsapp", "messaging", "personal contacts (one-to-one)",          "casual, short, informal"),
    ("org.telegram", "messaging", "friends or contacts",                    "casual or semi-formal, short"),
    ("com.discord", "social",     "community peers",                        "casual, community-specific slang ok"),
    ("com.linkedin", "social",    "professional network",                   "professional, polished, no jargon"),
    ("us.zoom",    "meeting",     "colleagues",                             "clear, professional, complete sentences"),
    ("outlook",   "email",      "professional contacts",                    "full sentences, formal tone, clear subject-action structure"),
    ("gmail",     "email",      "professional or personal contacts",        "full sentences, structured paragraphs"),
    (" mail",     "email",      "contacts",                                 "full sentences, appropriate formality"),
    ("teams",     "team chat",  "team peers (technical or business)",       "concise, direct, no greetings needed"),
    ("slack",     "team chat",  "colleagues or project peers",              "short, casual, no sign-offs"),
    ("word",      "document",   "future readers or collaborators",          "polished prose, formal, structured"),
    ("google docs","document",  "collaborators or future readers",          "clear prose, structured, professional"),
    ("notion",    "notes",      "self or small team",                       "structured notes, concise, headings ok"),
    ("whatsapp",  "messaging",  "personal contacts (one-to-one)",           "casual, short, informal"),
    ("telegram",  "messaging",  "friends or contacts",                      "casual or semi-formal, short"),
    ("discord",   "social",     "community peers (gaming/tech/hobby)",      "casual, community-specific slang ok"),
    ("twitter",   "social",     "broad anonymous audience",                 "punchy, concise, no fluff"),
    ("linkedin",  "social",     "professional network",                     "professional, polished, no jargon"),
    ("zoom",      "meeting",    "colleagues",                               "clear, professional, complete sentences"),
    ("notepad",   "notes",      "self",                                     "informal, shorthand ok"),
]


def _pb_reader_block(window_title):
    """Return a READER CONTEXT block from foreground window title, or '' if no match."""
    if not window_title:
        return ""
    title = window_title.lower()
    for keyword, category, audience, medium in _WINDOW_AUDIENCE:
        if keyword in title:
            return (
                "\n\nREADER CONTEXT (system-detected from foreground window — use to tune style only, NEVER echo back, NEVER mention):"
                f"\n- Active window: contains '{keyword}'"
                f"\n- Category: {category}"
                f"\n- Implied audience: {audience}"
                f"\n- Medium expectations: {medium}"
                "\n\nTune output for this audience and medium. Specifically:"
                "\n- DO NOT add greetings or sign-offs unless the medium expects them."
                "\n- MATCH the medium's brevity convention: chat = short, email = full sentences, document = polished prose."
                "\n- PRESERVE slang and informality when the audience expects it."
            )
    return ""


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

SITUATION_SEVERITY = {"default": 1.0, "high_stress": 1.5, "reading": 0.5}


def build_completion_prompt(partial_text, tone="casual", language_code="en", n=3):
    """Mid-block bridging prompt — single source for desktop + Cloud Function.

    The speaker froze mid-sentence on a speech block. Given the partial utterance
    they got out before freezing (passed as the user message), produce `n` natural
    ways to FINISH the sentence so they can tap one to bridge the block. Returns a
    system-prompt string. Kept deliberately tight: the speaker is frozen and
    waiting, so the consumer calls the FAST model, not extended thinking.
    """
    tone_rule = TONE_RULES.get(tone, TONE_RULES["casual"])
    lang_line = ""
    if language_code and language_code != "en":
        lang_line = (f"\nThe speaker is talking in language code '{language_code}'. "
                     "Write the completions in that language.\n")
    return (
        "You help someone who just froze mid-sentence (a speech block) finish what "
        "they were trying to say. You are given the partial utterance they managed "
        f"to get out before freezing. Propose exactly {n} natural, distinct ways the "
        "sentence could end.\n\n"
        f"Tone: {tone_rule}\n"
        f"{lang_line}"
        "Hard rules:\n"
        f"- Output exactly {n} lines, one option per line.\n"
        "- Each line is the COMPLETE sentence from the start — include the speaker's "
        "own words (cleaned of fillers and stutter repetitions) followed by a natural "
        "ending. Do NOT output only the continuation.\n"
        "- No numbering, no bullets, no quotes, no preamble, no commentary.\n"
        "- Each line is a sentence the speaker could say verbatim, under ~22 words.\n"
        "- Stay faithful to the partial intent; do not invent unrelated content."
    )


# ─── Multilingual lang-pack helpers (docs/l4_prompt_engineering_memo.md) ───
_LANG_PACK_CACHE = {}


def _lang_packs_dir():
    return Path(__file__).resolve().parent / "lang_packs"


def _load_lang_pack(code):
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


# ─── Prompt-section helpers ───
# build_prompt was a 450-line monolith with CC=65. Each helper below returns one
# discrete block (or "" if not applicable). Strings are preserved verbatim from
# the original — same prompts, just decomposed.

def _pb_severity_aggression(situation, speech_severity_mod, audio_duration_s, word_count):
    """Severity-based aggression hint + rate-gap signal, appended to the
    opening directive. Returns a string that begins with a leading space."""
    severity = SITUATION_SEVERITY.get(situation, 1.0) + speech_severity_mod
    note = ""
    if severity >= 1.4:
        note = (
            " Speaker is in a HIGH-STRESS context (phone/presentation/interview). "
            "Expect more disfluencies, heavier avoidance, more filler stacking. "
            "Be MORE aggressive in reconstructing — strip more, trust less of the literal words."
        )
    elif severity >= 1.1:
        note = (
            " Speaker's speech shows elevated pausing or slow rate. "
            "Apply moderate cleanup — fix grammar, strip fillers, smooth hesitations."
        )
    elif severity <= 0.6:
        note = (
            " Speaker is in a low-stress context. Expect near-fluent speech. "
            "Be conservative — minor cleanup only."
        )
    if speech_severity_mod > 0:
        note += f" [Speech metrics: severity_boost={speech_severity_mod:.1f}]"
    if audio_duration_s is not None and word_count is not None and audio_duration_s > 1.0:
        wps = word_count / audio_duration_s
        if wps < 1.5:
            note += (
                f" [Rate gap: {word_count} words in {audio_duration_s:.1f}s "
                f"= {wps:.2f} wps; normal fluent = 2.0-2.5 wps; "
                f"low ratio implies pre-smoothing pauses/blocks]"
            )
        elif wps > 4.0:
            note += (
                f" [Rate gap: {word_count} words in {audio_duration_s:.1f}s "
                f"= {wps:.2f} wps; high ratio implies cluttered/rushed delivery]"
            )
    return note


def _pb_layer3_user_context(profile, prior_rejections, style_examples):
    """L3+ block: user vocabulary/corrections + rejection history + style examples."""
    if not profile:
        return ""
    out_parts = []
    ctx = []
    if profile.get("vocabulary"):
        ctx.append(f"Preferred terms: {', '.join(profile['vocabulary'][:20])}")
    if profile.get("corrections"):
        pairs = [f"{k}->{v}" for k, v in list(profile["corrections"].items())[:10]]
        ctx.append(f"Known corrections: {'; '.join(pairs)}")
    if ctx:
        out_parts.append(
            "\nLAYER 3 PROFILE TERMS — AUTHORITATIVE:\n"
            + "\n".join(ctx)
            + "\nUse the exact saved spelling and capitalization whenever the ASR text "
              "is a plausible phonetic rendering of one of these terms. A known "
              "correction is not limited to an exact literal match: low-confidence "
              "neighbors may be different ASR guesses of the same intended word. "
              "Compare whole phrases as well as individual words. Never return an "
              "unchanged transcript while a plausible profile correction remains."
        )

    if prior_rejections:
        block = [
            "\n\nPERSISTENT REJECTION HISTORY (recent reconstructions this user "
            "rejected — DO NOT echo back, use only to avoid producing structurally "
            "similar text):"
        ]
        for i, prev in enumerate(prior_rejections, start=1):
            block.append(f'\n  {i}. "{prev}"')
        block.append(
            "\nThese don't fit this user's voice. Pick distinctively different "
            "word choices, sentence shapes, and rhythm. Variety in style across "
            "these examples beats imitation of any single one."
        )
        out_parts.append("".join(block))

    if style_examples:
        block = [
            "\n\nUSER STYLE EXAMPLES (recent reconstructions this user accepted "
            "as final — apply same style choices when relevant; DO NOT echo back):"
        ]
        for i, ex in enumerate(style_examples, start=1):
            block.append(f'\n  {i}. Raw: "{ex.get("raw", "")}" → Output: "{ex.get("output", "")}"')
        block.append(
            "\nThis user's voice across these examples is the target. Match "
            "sentence rhythm, comma placement, contraction usage, and overall "
            "tone — not specific words."
        )
        out_parts.append("".join(block))
    return "\n".join(out_parts)


def _pb_whisper_signals(whisper_low_conf, whisper_disagreements, layer):
    """Whisper low-confidence + multi-pass disagreement notes."""
    out_parts = []
    if whisper_low_conf:
        lc_notes = []
        block_notes = []
        for seg in whisper_low_conf[:5]:
            if seg.get("block_suspect"):
                block_notes.append(f"  \"{seg['text']}\" (no_speech_prob={seg['no_speech_prob']})")
            else:
                lc_notes.append(
                    f"  \"{seg['text']}\" (logprob={seg['avg_logprob']}, brown_risk={seg.get('brown_risk', 0.0)})"
                )
        if lc_notes:
            if layer >= 4:
                out_parts.append(
                    "\n⚠ WHISPER UNCERTAINTY — these segments have low decoder confidence "
                    "AND high stuttering risk. They are almost certainly transcription artifacts:\n"
                    + "\n".join(lc_notes)
                    + "\nReconstruct aggressively. Trust semantic context, not the literal words."
                )
            else:
                out_parts.append(
                    "\n⚠ LOW CONFIDENCE — Whisper's decoder was uncertain about these words:\n"
                    + "\n".join(lc_notes)
                    + "\nThese may be misheard. Use surrounding context to determine what was actually said."
                )
        if block_notes:
            if layer >= 4:
                out_parts.append(
                    "\n⚠ BLOCK SUSPECTS — Whisper nearly classified these as silence "
                    "(high no_speech_prob). For this speaker, silence before/during a word "
                    "is a BLOCK, not absence of speech. The text here is likely hallucinated "
                    "filler that Whisper invented to fill the gap:\n"
                    + "\n".join(block_notes)
                    + "\nDiscard these words entirely or replace with the word the speaker "
                    "was trying to say (use semantic context from surrounding words)."
                )
            else:
                out_parts.append(
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
        out_parts.append(
            "\n⚠ MULTI-PASS DISAGREEMENT — Whisper produced different words at these positions "
            "across 3 decoding temperatures. Disagreement = uncertain = likely misheard:\n"
            + "\n".join(dis_notes)
            + "\nThe truth is in the semantic context, not any single variant."
        )
    return "\n".join(out_parts)


def _pb_layer2_3_restate(profile, previous_outputs):
    """L2/L3 prose-restate (Strunk & White), self-correction, ASR examples,
    plus l1_pack/domain_pack injections and within-session regenerate signal."""
    out_parts = []
    out_parts.append(
        "\nALWAYS RESTATE — DO NOT RETURN INPUT UNCHANGED."
        "\nThe input is raw spoken material. The output is text someone will READ. "
        "CONVERT spoken cadence into written prose every time, even when input is fluent. "
        "Identity output is a failure mode."
        "\n\nApply these established prose rules (Strunk & White, federal Plain Language Guidelines):"
        "\n- Omit needless words. A sentence should contain no unnecessary words."
        "\n- Use the active voice. \"John threw the ball,\" not \"The ball was thrown by John.\""
        "\n- Use definite, specific, concrete language. \"It rained for a week,\" not \"a period of unfavorable weather.\""
        "\n- Sentence length should average 15-20 words. Break run-on speech into multiple short sentences."
        "\n- Keep subject and verb close together."
        "\n- Use everyday words. Avoid jargon unless the speaker used it specifically."
        "\n- Sentences should be simple, active, direct, and declarative."
        "\n- Drop verbal-tic discourse markers ('so', 'well', 'you know', 'like') even when not pure fillers."
        "\n\nThe speaker is brain-dumping in stream-of-consciousness order. "
        "They are offloading the structuring task to you. REORDER clauses, "
        "GROUP related ideas, and RESTRUCTURE into the flow a written reader expects "
        "(e.g., context → ask → close for an email; setup → question → specifics for a message; "
        "thesis → support → conclusion for an argument)."
        "\n\nHARD RULES while restating:"
        "\n- PRESERVE all numbers, dates, dollar amounts, addresses, names, proper nouns exactly as spoken."
        "\n- PRESERVE action-changing negation such as 'do not send', 'never share', "
        "and 'without approval'. Never turn a negative instruction into a positive one."
        "\n- PRESERVE the speaker's intent and the substance of every clause."
        "\n- DO NOT add information or invent details not present in the input."
        "\n- DO NOT soften, sanitize, or change profanity / strong language / slang. Output the words the speaker chose."
        "\n- DO NOT summarize away content; restate, don't compress."
        "\n- TREAT unfamiliar, invented-looking, or single-syllable unrecognized words as INTENTIONAL slang, brand names, or in-group vocabulary. "
        "Do not substitute them, do not assume transcription error, do not 'fix' them. "
        "Examples of what to PRESERVE without modification: 'rizz', 'bussin', 'no cap', 'mid', 'delulu', 'skibidi', 'ick', 'fanum tax', "
        "any proper noun the speaker emphasized, any startup or tool name the speaker said clearly."
    )
    out_parts.append(
        "\n\nSELF-CORRECTION — CANONICAL OVERWRITE:"
        "\nWhen the speaker uses 'I mean', 'actually', 'no wait', 'scratch that', 'let me rephrase', "
        "or similar mid-sentence revision markers, treat the content AFTER the marker as canonical "
        "and DISCARD the content before it. This is intentional self-correction, not disfluency."
        "\nExample: 'the meeting at 3pm, I mean 4pm' → 'the meeting at 4pm' (NOT '3pm 4pm', NOT '3pm')."
        "\nExample: 'I'm going to the s-s-s-the place' → 'I'm going to the place' (covert revision past a hard onset)."
        "\nExample: 'let's go to Italian, actually let's go to Thai' → 'let's go to Thai'."
    )
    out_parts.append(
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

    # L1-transfer pack — phonetic accent dies at ASR, syntactic/morphological/
    # lexical patterns survive in the transcript and are deterministically detectable.
    l1_block = l1_pack.prompt_injection(profile)
    if l1_block:
        out_parts.append(l1_block)

    # Domain pack — canonical-vocab list + phonetic-alias corrections.
    domain_block = domain_pack.prompt_injection(profile)
    if domain_block:
        out_parts.append(domain_block)

    # Within-session regenerate signal: previous outputs the user rejected.
    if previous_outputs:
        recent = list(previous_outputs)[-4:]
        out_parts.append(
            "\n\nThe speaker is asking for a DIFFERENT phrasing of the same intent. "
            "You have already produced these reconstructions, which the speaker rejected:"
        )
        for i, prev in enumerate(recent, start=1):
            out_parts.append(f'\n  {i}. "{prev}"')
        out_parts.append(
            "\nProduce a new reconstruction that preserves the same meaning but uses "
            "different word choices, sentence structure, and rhythm. Do not return any "
            "of the prior outputs verbatim or with only trivial edits."
        )
    return "\n".join(out_parts)


def _pb_current_layer_context(layer):
    """Give ASR cleanup the canonical name of the layer processing this take."""
    layer_names = {
        2: "Layer 2 reconstruction",
        3: "Layer 3 profile",
        4: "Layer 4 advanced assist",
    }
    current = layer_names.get(layer)
    if not current:
        return ""
    example = ""
    if layer == 2:
        example = (
            "\n- Example: while testing this layer, an ASR phrase such as "
            "'weakest reduction' should be corrected to 'Layer 2 reconstruction'."
        )
    return (
        "\n\nCURRENT PRODUCT CONTEXT:"
        f"\n- This recording is being processed in {current}."
        "\n- If the speaker is clearly testing or discussing the current app layer, "
        "correct phonetically similar ASR errors to this canonical layer name."
        "\n- Use this context only to resolve words the speaker attempted; never "
        "insert the layer name into unrelated dictation."
        + example
    )


L2_MAX_REWRITE_ATTEMPTS = 3


def is_effectively_unchanged(raw_text, reconstructed_text):
    """True when Layer 2 changed only case, punctuation, or whitespace."""
    def _words(text):
        return re.findall(r"\w+", (text or "").casefold(), flags=re.UNICODE)

    raw_words = _words(raw_text)
    return bool(raw_words) and raw_words == _words(reconstructed_text)


def layer2_rewrite_needs_retry(raw_text, reconstructed_text,
                               lost=None, invented=None):
    """Layer 2 must produce a non-identity rewrite that passes the guard."""
    return (
        not (reconstructed_text or "").strip()
        or is_effectively_unchanged(raw_text, reconstructed_text)
        or bool(lost)
        or bool(invented)
    )


def build_layer2_repair_instruction(raw_text, reconstructed_text,
                                    lost=None, invented=None):
    """Tell the model why its Layer 2 rewrite was rejected and require repair."""
    lost = list(lost or [])
    invented = list(invented or [])
    reasons = []
    if not (reconstructed_text or "").strip():
        reasons.append("- The previous answer was empty.")
    elif is_effectively_unchanged(raw_text, reconstructed_text):
        reasons.append(
            "- The previous answer merely repeated the transcript. "
            "Use different wording or sentence structure."
        )
    if lost:
        anchors = [item for item in lost if item != "<negation>"]
        if anchors:
            reasons.append(
                "- It dropped protected content. Preserve these exact items: "
                + ", ".join(repr(item) for item in anchors)
                + "."
            )
        if "<negation>" in lost:
            reasons.append(
                "- It changed negative meaning. Keep the original negation explicit."
            )
    if invented:
        reasons.append(
            "- It invented protected content. Remove these unsupported items: "
            + ", ".join(repr(item) for item in invented)
            + "."
        )
    return (
        "RECONSTRUCTION REPAIR REQUIRED.\n"
        + "\n".join(reasons)
        + "\nRewrite the original transcript again. Produce a materially different, "
        "natural reconstruction while preserving every fact and instruction. "
        "Return only the rewritten text on one line."
    )


def run_layer2_rewrite(raw_text, messages, rewrite_once, guard_once,
                       on_retry=None, max_attempts=L2_MAX_REWRITE_ATTEMPTS):
    """Run Layer 2 until it is both materially rewritten and guard-approved."""
    messages = list(messages)
    clean_text = ""
    guard_result = {"lost": [], "invented": []}
    attempts = 0
    for attempt_index in range(max_attempts):
        clean_text = (rewrite_once(messages, attempt_index) or "").strip()
        attempts += 1
        guard_result = guard_once(clean_text) or {"lost": [], "invented": []}
        lost = list(guard_result.get("lost") or [])
        invented = list(guard_result.get("invented") or [])
        if not layer2_rewrite_needs_retry(
            raw_text,
            clean_text,
            lost=lost,
            invented=invented,
        ):
            break
        if attempt_index + 1 >= max_attempts:
            break
        if on_retry:
            on_retry(attempts, clean_text, guard_result)
        messages.extend([
            {"role": "assistant", "content": clean_text},
            {
                "role": "user",
                "content": build_layer2_repair_instruction(
                    raw_text,
                    clean_text,
                    lost=lost,
                    invented=invented,
                ),
            },
        ])
    return clean_text, attempts, guard_result


def _pb_layer4_onset_hint(personal_onset_weights, profile):
    """L4 per-speaker hardest-phonemes line."""
    onset_weights = personal_onset_weights or profile.get("onset_weights", {})
    if not onset_weights:
        return ""
    ranked = sorted(onset_weights.items(), key=lambda x: -x[1])
    hard_onsets = [f"/{o}/ ({round(w*100)}%)" for o, w in ranked[:6] if w >= 0.4]
    if not hard_onsets:
        return ""
    return (
        f"\n⚠ THIS SPEAKER'S HARDEST PHONEMES: {', '.join(hard_onsets)}"
        "\nWhisper output near these onsets is unreliable — expect hallucinations, "
        "syllable drops, or phantom word insertions. Trust semantic context over "
        "literal transcription when words starting with these sounds look garbled."
    )


def _pb_layer4_covert_avoidance(profile):
    """L4 covert-avoidance pairs note."""
    covert = profile.get("covert_profile", {}).get("avoidance_pairs", {})
    if not covert:
        return ""
    covert_note = []
    for sit, words in list(covert.items())[:3]:
        for word, data in list(words.items())[:3]:
            subs = data.get("common_substitutes", [])[:2]
            if subs:
                covert_note.append(f"'{word}' → {subs} (avoidance of /{data.get('dominant_onset', '?')}/)")
    if not covert_note:
        return ""
    return (
        "\n⚠ KNOWN COVERT AVOIDANCE: speaker sometimes swaps these words: "
        + "; ".join(covert_note)
        + "\nIf you see a synonym where the original word would fit better, "
        "the original IS what they meant. Reconstruct with the intended word."
    )


def _pb_layer4_clinical_core(language_code):
    """L4 multilingual clinical block (the big one)."""
    _lang_code = _normalize_lang_code(language_code)
    _lang_name_str = _lang_name(_lang_code)
    _lang_fillers = _get_lang_fillers(_lang_code)
    _lang_natural_repeats = _get_lang_natural_repeats(_lang_code)
    _dialect_note = _get_lang_dialect_avoidance_note(_lang_code)
    _timing_note = _get_lang_syllable_timing_note(_lang_code)

    out_parts = []
    out_parts.append(
        f"\nThe speaker has a speech disfluency. Language: {_lang_code.upper()} ({_lang_name_str}). "
        "Raw transcription is evidence of intent, not truth. "
        "Reconstruct the intended message. Preserve FULL meaning."
    )
    if _lang_fillers:
        out_parts.append(f"\n\nFILLERS TO STRIP ({_lang_code}): {', '.join(_lang_fillers)}")
    if _lang_natural_repeats:
        out_parts.append(
            f"\n\nEMPHATIC PATTERNS — DO NOT STRIP in {_lang_code}: {', '.join(_lang_natural_repeats)}"
            f"\nThese are pragmatically meaningful in {_lang_name_str}, not stuttering."
        )
    out_parts.append("\n\nOvert disfluencies — strip and reconstruct:")
    out_parts.append(f"\n- Part-word repetitions: {_get_lang_part_word_example(_lang_code)}")
    out_parts.append("\n- Whole-word repetitions (NOT matching the emphatic allow-list above)")
    out_parts.append(f"\n- Prolongations: {_get_lang_prolongation_example(_lang_code)}")
    out_parts.append(f"\n- Epenthetic insertions during blocks: {_get_lang_epenthesis_note(_lang_code)}")
    out_parts.append("\n- Blocks: silence or frozen onset before a word (locked articulators)")
    out_parts.append("\n- Tremors: lip/jaw quivering during a fixation")
    out_parts.append("\n- Secondary behaviors: eye blinks, foot taps, head movements during blocks")
    out_parts.append("\n- False starts and restarts")

    out_parts.append("\n\nCovert avoidance — recognize as avoidance behavior, not content:")
    out_parts.append("\n- Filler clusters before a content word = postponement (see filler list above)")
    out_parts.append("\n- Synonym substitution = avoiding a feared word")
    out_parts.append("\n- Circumlocution = talking around a feared word")
    out_parts.append("\n- Sentence abandonment = dropping thought before feared word ('Oh, never mind')")
    out_parts.append("\n- Covert interruption = jumping in while someone talks to mask onset difficulty")
    out_parts.append(
        "\n- Mazes: extended filler runs adding no information. DISTINCT from cluttered "
        "rapid speech — do not over-strip if the speaker's speech is globally rapid."
    )
    if _dialect_note:
        out_parts.append(f"\n{_dialect_note}")

    out_parts.append("\n\nAnticipatory behavior:")
    out_parts.append(
        "\n- A pause or silence BEFORE a content word with a hard onset MAY INDICATE anticipatory fear"
    )
    out_parts.append(
        "\n- Confidence increases when a filler cluster appears in the preceding 1–3 words "
        "AND the following word begins with a documented hard onset"
    )
    out_parts.append("\n- Treat as a block candidate, not certainty")
    if _timing_note:
        out_parts.append(f"\n{_timing_note}")

    out_parts.append("\n\nWhisper ASR failure modes on disfluent speech:")
    out_parts.append("\n- HALLUCINATION DURING BLOCKS: silence → Whisper generates phantom text.")
    out_parts.append(
        "\n  Known hallucination strings to discard: 'thank you', 'thanks for watching', "
        "'subscribe', 'like and subscribe', 'transcribed by', 'captions by', 'otter.ai'."
    )
    if _lang_code != "en":
        out_parts.append(
            f"\n  In {_lang_name_str} transcripts, English phrases appearing mid-utterance "
            "are likely Whisper hallucinations — discard them."
        )
    out_parts.append("\n- SYLLABLE DELETION: repeated syllables collapsed or dropped")
    out_parts.append("\n- PHANTOM INSERTIONS: prolongations → Whisper hallucinates similar-sounding words")
    out_parts.append(f"\n- {_get_lang_epenthesis_corruption_note(_lang_code)}")
    out_parts.append("\n- PAUSE HALLUCINATION: long pauses → Whisper generates filler text (see above)")

    out_parts.append("\n\n")
    out_parts.append(_get_lang_few_shot_examples(_lang_code))

    out_parts.append(
        "\n\nDo not mistake disfluency for emphasis — but PRESERVE the emphatic patterns listed above."
        "\nReconstruct within the speaker's established dialect — do not substitute dialectal forms."
        "\nWhen uncertain, prefer conservative cleanup over aggressive rewriting."
    )

    _onset_caveat = _get_lang_onset_caveat(_lang_code)
    if _onset_caveat:
        out_parts.append(f"\n{_onset_caveat}")
    if _lang_has_no_onset_research(_lang_code):
        out_parts.append(
            f"\n\nONSET NOTE: No published phoneme-difficulty research exists for {_lang_code} "
            "as of April 2026. Do not apply English-derived onset assumptions. Focus on word-level "
            "repetitions, prolongations, filler clusters, and Whisper hallucination strings."
        )
    return "".join(out_parts)


def _pb_layer4_block(profile, language_code, personal_onset_weights,
                     personal_dominant_onsets, predicted_triggers):
    """Full L4 prompt block — onset hint + covert + clinical core + triggers."""
    out_parts = []
    onset_hint = _pb_layer4_onset_hint(personal_onset_weights, profile)
    if onset_hint:
        out_parts.append(onset_hint)
    covert_note = _pb_layer4_covert_avoidance(profile)
    if covert_note:
        out_parts.append(covert_note)

    out_parts.append(_pb_layer4_clinical_core(language_code))

    if profile.get("trigger_words"):
        out_parts.append(f"\nKnown trigger words: {', '.join(profile['trigger_words'])}")

    if personal_dominant_onsets:
        onset_desc = ", ".join(f"/{d['onset']}/ ({d['pct']}%)" for d in personal_dominant_onsets)
        out_parts.append(
            f"\nThis speaker's personal block pattern: {onset_desc} of triggers. "
            "Words starting with these sounds are HIGH PRIORITY for reconstruction — "
            "expect heavier disfluency on these onsets specifically."
        )

    if predicted_triggers:
        flagged = [f"{w}({r})" for w, r in predicted_triggers[:10]]
        out_parts.append(f"\nPhonetically predicted high-risk words in this utterance: {', '.join(flagged)}")

    return "\n".join(out_parts)


def _pb_paralinguistic_events(paralinguistic_events):
    """Lavrentiy L5 paralinguistic-events block."""
    if not paralinguistic_events:
        return ""
    notes = []
    for ev in paralinguistic_events[:8]:
        notes.append(
            f"  [{ev['type']}] at {ev['start_s']:.1f}s–{ev['end_s']:.1f}s "
            f"(confidence={ev['confidence']}, HNR={ev.get('hnr_db', '?')}dB)"
        )
    if not notes:
        return ""
    return (
        "\n⚠ PARALINGUISTIC EVENTS DETECTED — the following non-speech sounds were "
        "found in the audio. Whisper likely hallucinated words in these windows. "
        "IGNORE or DISCARD any transcribed text that falls within ±1 second of "
        "these timestamps — it is not speech:\n"
        + "\n".join(notes)
        + "\nReconstruct using surrounding context only. Do not try to interpret "
        "non-speech sounds as words."
    )


def build_prompt(
    raw_text,
    *,
    tone="casual",
    layer=2,
    profile=None,
    situation="default",
    whisper_low_conf=None,
    whisper_disagreements=None,
    speech_severity_mod=0.0,
    paralinguistic_events=None,
    prosodic_context=None,
    language_code="en",
    audio_duration_s=None,
    word_count=None,
    previous_outputs=None,
    prior_rejections=None,
    style_examples=None,
    personal_onset_weights=None,
    personal_dominant_onsets=None,
    predicted_triggers=None,
    window_title=None,
    preceding_context=None,
    script_prep_context=None,
    compression_ratio_note=None,
):
    """Assemble the reconstruction system prompt.

    Pure function — no API calls, no side effects, no module-level state reads.
    All inputs explicit; all output is the concatenated system-prompt string.

    Layer semantics:
      L1: not used (handled outside — disfluency strip only)
      L2: ASR cleanup + tone
      L3: + user profile (vocab, corrections, rejection/style history)
      L4: + clinical disfluency context, multilingual lang pack, onset weights
    """
    profile = profile or {}
    tone_rule = TONE_RULES.get(tone, TONE_RULES["casual"])

    has_cyrillic = any('Ѐ' <= c <= 'ӿ' for c in raw_text)
    lang_note = " Speaker is bilingual (English/Russian) and may mix languages." if has_cyrillic else ""
    aggression_note = _pb_severity_aggression(situation, speech_severity_mod, audio_duration_s, word_count)

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
        "NEGATION IS A PROTECTED ANCHOR. Action-changing negatives such as "
        "'do not send', 'never share', and 'without approval' must remain "
        "negative. The idiom 'whether X or not' may become 'whether X' because "
        "the uncertainty remains explicit.",
        "Do NOT censor, sanitize, or soften the speaker's language. Profanity, slang, "
        "harsh words, and strong language must be preserved EXACTLY as spoken. "
        "If the speaker said 'fuck', output 'fuck'. If the speaker said 'steal', output 'steal'. "
        "Do not substitute softer synonyms (e.g. do not change 'steal' to 'borrow'). "
        "Your job is to clean up SPEECH ARTIFACTS, not to edit the speaker's word choices.",
        "Output ONLY the reconstructed text.",
        "Do not include any preamble, explanation, meta-commentary, or notes about what you changed.",
        "Do not use Markdown formatting: no asterisks, no backticks, no bullet points, no headers, no quotation marks around the output.",
        "Do not use emojis or emoticons.",
        "Output exactly one line containing only the reconstructed sentence or paragraph, with no leading or trailing whitespace.",
    ]

    if profile.get("filler_words"):
        parts.append(f"\nStrip these fillers: {', '.join(profile['filler_words'][:25])}")

    if script_prep_context:
        parts.append(
            "\nSCRIPT PREP CONTEXT (provided by the speaker before dictation):\n"
            + str(script_prep_context)[:6000]
            + "\nUse this only to resolve intended names, terminology, topic, and phrasing. "
              "Never quote, repeat, acknowledge, or invent content from it unless the speaker "
              "actually dictated that content."
        )

    if preceding_context:
        parts.append(
            "\nTEXT ALREADY IN THE TARGET FIELD (context only — never repeat or acknowledge):\n"
            + str(preceding_context)[-500:]
        )

    if compression_ratio_note:
        parts.append("\nSPEECH-RATE SIGNAL:\n" + str(compression_ratio_note)[:500])

    current_layer_block = _pb_current_layer_context(layer)
    if current_layer_block:
        parts.append(current_layer_block)

    if layer >= 3:
        l3_block = _pb_layer3_user_context(profile, prior_rejections, style_examples)
        if l3_block:
            parts.append(l3_block)

    whisper_block = _pb_whisper_signals(whisper_low_conf, whisper_disagreements, layer)
    if whisper_block:
        parts.append(whisper_block)

    # L2/L3 prose-restate block (Strunk & White + restructure + self-correction + ASR examples)
    if 2 <= layer <= 3:
        parts.append(_pb_layer2_3_restate(profile, previous_outputs))

    # Reader context from the foreground window — Slack wants short and
    # sign-off-free, Outlook wants full sentences, Word wants prose.
    #
    # This used to be L2/L3 only, which meant L4 — the layer for the hardest
    # speech — was the one flying blind on register. That is backwards: a
    # speaker managing a block has the least attention spare for noticing the
    # output is pitched wrong for where it is about to land, and is the least
    # likely to go and flip a tone switch first. Register detection is worth
    # more at L4 than anywhere else, not less.
    #
    # Unlike the l1/domain packs above, this does not duplicate anything in the
    # L4 clinical block — that block carries disfluency and onset context and
    # says nothing about audience or medium.
    reader_block = _pb_reader_block(window_title)
    if reader_block:
        parts.append(reader_block)

    # L4 clinical block — full disfluency context, multilingual lang pack, onset weights.
    #
    # NOTE: L4 deliberately does NOT receive the l1_pack / domain_pack injections.
    # Those are attached inside _pb_layer2_3_restate() and are L2/L3-only by design
    # (decision recorded in the 2026-04-28 README entry). L4 carries its own
    # first-language and clinical framing via _pb_layer4_block, so injecting the
    # packs here would duplicate that context and dilute the clinical prompt.
    # This is intentional, not an oversight — it has been re-flagged as a bug by
    # multiple review passes.
    if layer >= 4:
        l4_block = _pb_layer4_block(profile, language_code, personal_onset_weights,
                                     personal_dominant_onsets, predicted_triggers)
        if l4_block:
            parts.append(l4_block)

    # Paralinguistic event context (lavrentiy L5).
    para_block = _pb_paralinguistic_events(paralinguistic_events)
    if para_block:
        parts.append(para_block)

    # Prosodic bridging (lavrentiy L5.5) — caller passes a pre-formatted block.
    if prosodic_context:
        parts.append("\n" + prosodic_context)

    return "\n".join(parts)
