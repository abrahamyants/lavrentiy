"""Deterministic meaning guard for the shared reconstruction path.

Why this exists
---------------
`lavrentiy.py` has had `_check_critical_retention` for a long time: a free,
rule-based check that names, numbers, dates and negations survived
reconstruction. The Cloud Function never had an equivalent, so the guard
protected direct-key desktop users and nobody else — signed-in desktop users
and every WiM Android user run through this module's caller instead. Same
shape as the L4 model-parity gap: a feature that only exists on one of the
three distribution paths.

This module closes that gap and adds the direction the desktop check was
missing.

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

Number handling is deliberately loose in one direction: "four thousand two
hundred dollars" legitimately becomes "$4,200", so a figure in the output is
only treated as invented when the input contained no digits AND no number
words at all.
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

PROPER_NOUN_EXCLUDE = {
    "A", "An", "And", "Are", "As", "At", "But", "By", "Can", "Could",
    "Do", "For", "From", "How", "I", "If", "In", "Is", "It", "My",
    "No", "Not", "On", "Or", "Please", "Set", "Show", "Tell", "The",
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

    for term in (vocabulary or []):
        term = str(term).strip()
        if len(term) < 2:
            continue
        if re.search(r"\b" + re.escape(term.lower()) + r"\b", raw_lower):
            critical.append(term)

    clean_lower = clean_text.lower()
    seen = set()
    lost = []
    for t in critical:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        if key not in clean_lower:
            lost.append(t)

    if NEGATION_RE.search(raw_text) and not NEGATION_RE.search(clean_text):
        lost.append("<negation>")
    return lost


def check_fabrication(raw_text, clean_text):
    """Anchors that appear in the output but were never in the input.

    Catches the failure the retention check cannot: the reconstructor filling a
    destroyed span with a confident, plausible, wrong name or figure. Only
    proper nouns and figures are checked, because those are the ones that cause
    real damage when pasted and the ones a rule can identify without guessing.
    """
    raw_text = raw_text or ""
    clean_text = clean_text or ""
    raw_lower = raw_text.lower()
    invented = []

    for token in _proper_nouns(clean_text):
        if token.lower() not in raw_lower:
            invented.append(token)

    # A figure in the output is only suspicious when the input offered nothing
    # numeric at all — otherwise "four thousand two hundred" -> "$4,200" would
    # be flagged, and that is a correct reconstruction.
    if CRITICAL_TOKEN_RE.search(clean_text):
        raw_has_number = bool(
            CRITICAL_TOKEN_RE.search(raw_text) or NUMBER_WORD_RE.search(raw_text)
        )
        if not raw_has_number:
            invented.extend(CRITICAL_TOKEN_RE.findall(clean_text))

    return invented


def guard(raw_text, clean_text, vocabulary=None):
    """Full check. Returns {ok, lost, invented}.

    ok is False when reconstruction either dropped a meaning anchor or produced
    one out of nothing. Callers in SAFE mode should fall back to the
    rule-stripped raw text rather than paste a reconstruction that failed this.
    """
    lost = check_retention(raw_text, clean_text, vocabulary=vocabulary)
    invented = check_fabrication(raw_text, clean_text)
    return {"ok": not lost and not invented, "lost": lost, "invented": invented}
