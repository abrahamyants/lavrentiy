"""Deterministic meaning guard for the shared reconstruction path.

Why this exists
---------------
`lavrentiy.py` has had `_check_critical_retention` for a long time: a free,
rule-based check that names, numbers, dates and negations survived
reconstruction. The Cloud Function itself never had an equivalent, so a
signed-in desktop user got no server-side check.

**WiM Android was already covered and this module did not close a gap for it.**
`ReconstructClient.computeRiskFlags` (with `checkCriticalTokens` and
`RiskFlagsTest`) has run client-side on the backend reconstruction path since
2026-06-03, added precisely to stop the server shipping reconstructions with
missing amounts or dates into a user's text field. An earlier version of this
docstring claimed WiM users were unprotected. That was wrong — written after
checking this directory and not the Android source.

So what this module actually adds: the same protection for the signed-in
desktop path, in one shared place, plus the direction BOTH existing
implementations were missing.

Two directions, not one
-----------------------
The original check only catches anchors that DISAPPEAR (reconstruction dropped
a name the speaker said). The 2026-07-25 stress corpus surfaced the opposite
and more dangerous failure: anchors that APPEAR. Given

    "please forward the file to subscribe at the london office"

— where a speech block destroyed the recipient's name and Whisper emitted its
own artifact in the gap — the reconstructor produced

    "Please forward the file to Henderson at the London office."

Henderson was never said. It came out of the speaker's own profile vocabulary
and would have been pasted into a real email. Loss is recoverable by falling
back to raw text; invention is not, because it is fluent, confident, and looks
correct. So `guard()` checks both directions.

Deliberate limits
-----------------
This is a rule-based check, not a semantic validator, and it is honest about
what it cannot do:

  * It catches invented PROPER NOUNS and invented FIGURES — the high-stakes
    cases that end up in emails and invoices.
  * It does NOT catch invented common nouns. From the same corpus, "I need to
    pick up the <block> from the store" became "...pick up the present...",
    and no rule distinguishes that from a legitimate reconstruction. Catching
    it needs a model, not a regex.
  * It cannot recover information the ASR never captured. If a block ate the
    word "not" before the text arrived, nothing downstream can know. The guard
    only ensures reconstruction does not make things worse.

Number handling compares integer values across figures and spelled-out runs,
so "four thousand two hundred dollars" may become "$4,200", while "$1,200"
is rejected as numeric drift.
"""

import re

# ── Anchors worth protecting ────────────────────────────────────────────
# Kept byte-identical in intent to lavrentiy.py's copies so the two paths
# agree on what counts as critical. If you change one, change both.

CRITICAL_TOKEN_RE = re.compile(
    r'\b(?:\d+(?:[.,]\d+)?%?|\$?\d+(?:,\d{3})*(?:\.\d+)?)\b'
)
NEGATION_RE = re.compile(
    r"\b(?:no|not|never|neither|nor|without|cannot|can't|won't|don't|doesn't|"
    r"didn't|isn't|aren't|wasn't|weren't|shouldn't|wouldn't|couldn't|mustn't)\b",
    re.IGNORECASE,
)
DATE_WORD_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b",
    re.IGNORECASE,
)
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{1,}\b")
TITLE_RE = re.compile(
    r"\b(?:doctor|dr|professor|prof|nurse|officer|detective|judge|attorney|counsel|"
    r"reverend|father|sister|rabbi|imam|senator|governor|mayor|chief|captain|"
    r"sergeant|lieutenant|colonel|general|admiral|principal|dean|coach|"
    r"mr|mrs|ms|miss|sir|madam|ma'am)\b\.?",
    re.IGNORECASE,
)

PROPER_NOUN_EXCLUDE = {
    "A", "An", "And", "Are", "As", "At", "But", "By", "Can", "Could",
    "Do", "For", "From", "How", "I", "If", "In", "Is", "It", "My",
    "No", "Not", "Okay", "On", "Or", "Please", "Set", "Show", "Tell", "The",
    "This", "To", "Turn", "What", "When", "Where", "Which", "Who", "Why",
    "Will", "With", "Would", "You", "Your",
    # Additional sentence-openers and auxiliaries that get capitalised by
    # reconstruction and would otherwise read as invented names.
    "Actually", "After", "Also", "Any", "Be", "Been", "Before", "Both",
    "Did", "Does", "Every", "Get", "Give", "Going", "Had", "Has", "Have",
    "He", "Her", "Here", "His", "Just", "Let", "Like", "Make", "May",
    "Me", "Might", "Must", "Need", "Never", "Now", "Of", "Once", "One",
    "Only", "Our", "Out", "Over", "Say", "See", "She", "Should", "Since",
    "So", "Some", "Still", "Such", "Than", "That", "Their", "Them", "Then",
    "There", "These", "They", "Those", "Though", "Through", "Thus", "Too",
    "Under", "Until", "Up", "Us", "Was", "We", "Were", "While", "Yes",
    "Yet", "Its", "Was", "Whether",
}

# Spelled-out figures. Presence of any of these in the input means a numeric
# token in the output is a reformatting, not an invention.
NUMBER_WORD_RE = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|half|quarter|dozen|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b",
    re.IGNORECASE,
)


def _proper_nouns(text):
    return [
        t for t in PROPER_NOUN_RE.findall(text or "")
        if t not in PROPER_NOUN_EXCLUDE
    ]


def check_retention(raw_text, clean_text, vocabulary=None):
    """Anchors present in the input that did not survive reconstruction.

    Port of lavrentiy.py `_check_critical_retention`, plus a fix for a blind
    spot the original has: it finds names by looking for Capitalised words, but
    disfluent ASR output is frequently all lowercase, so "call henderson about
    the marriott booking" contains no detectable names and losing them raises
    no flag.

    `vocabulary` closes most of that gap. The profile already carries the
    speaker's own names and terms — exactly the words that matter and exactly
    the ones ASR mangles — so any vocabulary entry present in the input is
    treated as critical regardless of case.

    Remaining limit, stated plainly: a name that is neither capitalised in the
    input nor in the speaker's vocabulary cannot be detected as lost. That
    needs a model, not a regex.
    """
    raw_text = raw_text or ""
    clean_text = clean_text or ""
    raw_lower = raw_text.lower()

    critical = list(CRITICAL_TOKEN_RE.findall(raw_text))
    critical.extend(DATE_WORD_RE.findall(raw_text))
    critical.extend(_proper_nouns(raw_text))
    raw_titles = {
        match.group(0).rstrip(".").lower()
        for match in TITLE_RE.finditer(raw_text)
    }
    critical.extend(
        match.group(0).rstrip(".")
        for match in TITLE_RE.finditer(raw_text)
    )

    for term in (vocabulary or []):
        term = str(term).strip()
        if len(term) < 2:
            continue
        if re.search(r"\b" + re.escape(term.lower()) + r"\b", raw_lower):
            critical.append(term)

    clean_lower = clean_text.lower()
    # Numeric anchors are compared BY VALUE, not as literal substrings. A digit
    # token from the input had to appear verbatim in the output, so a correct
    # reconstruction that spelled the figure out — "4200" -> "four thousand two
    # hundred", "$1,000" -> "1000" — read as a lost anchor and the guard threw
    # the whole reconstruction away. Layer 4 writes prose and spells figures out
    # routinely, so the layer that rewrites hardest was the one most often
    # rejected for being right.
    numeric_tokens = {m.lower() for m in CRITICAL_TOKEN_RE.findall(raw_text)}
    clean_numeric = numeric_values(clean_text)
    clean_titles = {
        match.group(0).rstrip(".").lower()
        for match in TITLE_RE.finditer(clean_text)
    }
    seen = set()
    lost = []
    for t in critical:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        if key in raw_titles:
            retained = key in clean_titles
        elif key in numeric_tokens:
            value = _numeric_token_value(t)
            retained = key in clean_lower or (
                value is not None and value in clean_numeric
            )
        else:
            retained = key in clean_lower
        if not retained:
            lost.append(t)

    raw_whether_or_not = bool(re.search(
        r"\bwhether\b[^.?!]*\bor\s+not\b", raw_text, re.IGNORECASE
    ))
    clean_keeps_uncertainty = bool(re.search(
        r"\b(?:whether|if)\b", clean_text, re.IGNORECASE
    ))
    if (
        NEGATION_RE.search(raw_text)
        and not NEGATION_RE.search(clean_text)
        and not (raw_whether_or_not and clean_keeps_uncertainty)
    ):
        lost.append("<negation>")
    return lost


# Whisper's stock output when it is decoding silence — training-data leakage
# from captioned video. Their presence in a transcript means a span of the
# recording produced no speech, which for this user usually means a block.
HALLUCINATION_ARTIFACT_RE = re.compile(
    r"(thanks?\s+for\s+watching|thank\s+you\s+for\s+watching|"
    r"don'?t\s+forget\s+to\s+subscribe|please\s+subscribe|\bsubscribe\b|"
    r"transcribed\s+by|subtitles?\s+by|amara\.org|otter\.ai|"
    r"\[BLANK_AUDIO\]|\[INAUDIBLE\]|\[MUSIC\])",
    re.IGNORECASE,
)

# Function words reconstruction is free to add, remove or swap. Anything not in
# here and long enough is treated as carrying meaning.
_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "there", "here", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must", "to", "of", "in",
    "on", "at", "by", "for", "with", "from", "into", "about", "as", "so", "not",
    "no", "yes", "it", "its", "i", "you", "your", "we", "our", "they", "them",
    "their", "he", "she", "his", "her", "him", "me", "my", "mine", "us", "who",
    "what", "when", "where", "why", "how", "which", "just", "very", "really",
    "some", "any", "all", "both", "each", "more", "most", "other", "such",
    "only", "own", "same", "too", "up", "out", "down", "over", "under", "again",
    "get", "got", "go", "going", "went", "let", "like", "want", "need", "make",
    "made", "take", "took", "come", "came", "know", "think", "say", "said",
    "tell", "told", "please", "okay", "well", "now", "also", "still", "back",
}


def _content_words(text):
    """Meaning-carrying words: not function words, at least four characters."""
    return [
        w for w in re.findall(r"[A-Za-z']{4,}", text or "")
        if w.lower() not in _FUNCTION_WORDS
    ]


def _has_source(word, raw_lower):
    """True if `word` plausibly derives from something in the input.

    Prefix comparison on the first five characters absorbs the ordinary
    inflection reconstruction performs — prescription/prescriptions,
    call/called, meet/meeting — without needing a stemmer.
    """
    w = word.lower()
    if w in raw_lower:
        return True
    stem = w[:5]
    return any(t.startswith(stem) for t in re.findall(r"[a-z']+", raw_lower))


def check_fabrication(raw_text, clean_text):
    """Anchors that appear in the output but were never in the input.

    Catches the failure the retention check cannot: the reconstructor filling a
    destroyed span with a confident, plausible, wrong value. Loss is
    recoverable by falling back to raw; invention is not, because it reads as
    correct.

    Names and figures are checked unconditionally — those cause real damage in
    an email or an invoice and a rule can identify them without guessing.

    Ordinary words are checked ONLY when the input contains a Whisper
    hallucination artifact. That gate matters: reconstruction is allowed to
    rephrase at L2/L3, so flagging every unsourced content word would fire on
    legitimate rewording constantly. But when the input contains "thanks for
    watching", a span of that recording was silence — and a confident new noun
    appearing where the silence was is the model filling a hole it cannot see
    into. That is the "pick up the <block> from the store" -> "pick up the
    prescription" case, which the same input produced twice with two different
    objects.
    """
    raw_text = raw_text or ""
    clean_text = clean_text or ""
    raw_lower = raw_text.lower()
    invented = []

    product_layer = re.search(
        r"\bLayer\s+([1-4])\s+(?:transcription|reconstruction|profile|advanced assist)\b",
        clean_text,
        re.IGNORECASE,
    )
    raw_has_product_context = bool(re.search(
        r"\b(?:layer|transcription|reconstruction|reduction|profile|advanced)\b",
        raw_text,
        re.IGNORECASE,
    ))

    for token in _proper_nouns(clean_text):
        if (
            token.lower() == "layer"
            and product_layer
            and raw_has_product_context
        ):
            continue
        if token.lower() not in raw_lower:
            invented.append(token)

    if HALLUCINATION_ARTIFACT_RE.search(raw_text):
        for word in _content_words(clean_text):
            if word in invented:
                continue
            if not _has_source(word, raw_lower):
                invented.append(word)

    # A figure in the output is only suspicious when the input offered nothing
    # numeric at all — otherwise "four thousand two hundred" -> "$4,200" would
    # be flagged, and that is a correct reconstruction.
    if CRITICAL_TOKEN_RE.search(clean_text):
        raw_has_number = bool(
            CRITICAL_TOKEN_RE.search(raw_text) or NUMBER_WORD_RE.search(raw_text)
        )
        if not raw_has_number:
            for figure in CRITICAL_TOKEN_RE.findall(clean_text):
                if (
                    product_layer
                    and raw_has_product_context
                    and figure == product_layer.group(1)
                ):
                    continue
                invented.append(figure)

    return invented


_NUMBER_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_SCALES = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}


def _numeric_token_value(token):
    normalized = token.replace(",", "").lstrip("$").rstrip("%")
    try:
        value = float(normalized)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else None


def numeric_values(text):
    """Return integer values stated as figures or spelled-out number runs."""
    values = {
        value
        for value in (
            _numeric_token_value(match.group(0))
            for match in CRITICAL_TOKEN_RE.finditer(text or "")
        )
        if value is not None
    }

    current = 0
    total = 0
    saw_number = False

    def flush():
        nonlocal current, total, saw_number
        if saw_number:
            values.add(total + current)
        current = 0
        total = 0
        saw_number = False

    for word in re.findall(r"[a-z]+", (text or "").lower()):
        if word in _NUMBER_UNITS:
            current += _NUMBER_UNITS[word]
            saw_number = True
        elif word == "hundred" and saw_number:
            current *= 100
        elif word in _NUMBER_SCALES and saw_number:
            total += current * _NUMBER_SCALES[word]
            current = 0
        elif word == "and" and saw_number:
            continue
        else:
            flush()
    flush()
    return values


def check_numeric_drift(raw_text, clean_text):
    """Figures in the rewrite whose numeric value was not stated in the input.

    Both representations are checked. CRITICAL_TOKEN_RE matches digits only, so
    for a long time an output that kept the number in WORDS produced no matches
    at all and every change passed: "four thousand two hundred" -> "five
    thousand three hundred" was invisible, as were "two billion" -> "two
    million" and "twenty copies" -> "thirty copies". Layer 4 writes prose and
    routinely keeps figures spelled out, so the layer that rewrites hardest was
    the one the check could not see.
    """
    raw_values = numeric_values(raw_text)
    if not raw_values:
        return []
    drifted = []
    seen = set()
    for match in CRITICAL_TOKEN_RE.finditer(clean_text or ""):
        value = _numeric_token_value(match.group(0))
        if value is not None and value not in raw_values:
            drifted.append(match.group(0))
            seen.add(value)
    for value in sorted(numeric_values(clean_text or "")):
        if value not in raw_values and value not in seen:
            drifted.append(str(value))
    return drifted


def guard(raw_text, clean_text, vocabulary=None):
    """Full check. Returns {ok, lost, invented}.

    ok is False when reconstruction either dropped a meaning anchor or produced
    one out of nothing. Callers in SAFE mode should fall back to the
    rule-stripped raw text rather than paste a reconstruction that failed this.
    """
    lost = check_retention(raw_text, clean_text, vocabulary=vocabulary)
    invented = list(dict.fromkeys(
        check_fabrication(raw_text, clean_text)
        + check_numeric_drift(raw_text, clean_text)
    ))
    return {"ok": not lost and not invented, "lost": lost, "invented": invented}
