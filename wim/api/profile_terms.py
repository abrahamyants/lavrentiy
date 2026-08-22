"""Conservative Layer 3 recovery of profile corrections and vocabulary.

ASR often returns a phonetic neighbor instead of the exact saved correction
key: ``cloth -> claude`` is useless when the recognizer emits ``count``.
Multiword preferred terms have the same problem: token-by-token matching cannot
recover ``yellow flag -> YOLO flag``.

This module matches whole phrases with Double Metaphone. Approximate matching
is deliberately limited to explicit correction pairs inside ASR-marked
low-confidence text. Preferred vocabulary requires an exact phonetic match
unless the literal term is already present. That keeps common profile words
from rewriting unrelated fluent speech.
"""

import re

try:
    from metaphone import doublemetaphone as _doublemetaphone
except ImportError:  # Tests and old desktop builds degrade to exact matching.
    _doublemetaphone = None


_WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)?", re.UNICODE)
_APPROXIMATE_BLOCKLIST = {
    "a", "an", "and", "are", "be", "been", "being", "but", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "he", "her",
    "him", "his", "i", "if", "in", "is", "it", "its", "may", "me", "might",
    "must", "my", "no", "not", "of", "on", "or", "our", "shall", "she",
    "should", "so", "that", "the", "their", "them", "they", "this", "those",
    "to", "us", "was", "we", "were", "will", "with", "would", "you", "your",
    # High-frequency content words. The list above is function words only,
    # which left everyday verbs open to phonetic capture by a profile term
    # on the vocabulary path. This only blocks approximate/phonetic recovery;
    # exact saved corrections still run before this candidate loop.
    "get", "gets", "getting", "got", "give", "gives", "given", "go", "goes",
    "going", "gone", "went", "come", "comes", "coming", "came", "take",
    "takes", "taking", "took", "make", "makes", "making", "made", "need",
    "needs", "needed", "want", "wants", "wanted", "know", "knows", "knew",
    "think", "thinks", "thought", "say", "says", "said", "see", "sees",
    "saw", "seen", "look", "looks", "looking", "tell", "tells", "told",
    "ask", "asks", "asked", "work", "works", "working", "call", "calls",
    "called", "try", "tries", "tried", "put", "puts", "keep", "keeps",
    "let", "lets", "help", "helps", "show", "shows", "run", "runs",
    "move", "moves", "hold", "holds", "bring", "brings", "write", "writes",
    "send", "sends", "sent", "sending", "read", "reads", "find", "finds",
    "found", "use", "uses", "used", "mean", "means", "meant", "set",
    "sets", "start", "starts", "stop", "stops", "here", "there", "then",
    "than", "when", "what", "who", "how", "why", "where", "all", "any",
    "just", "like", "now", "only", "out", "over", "some", "such", "up",
    "very", "well", "back", "down", "off", "one", "two", "day", "days",
    "time", "thing", "things", "good", "new", "old", "same", "next",
    "last", "first", "about", "after", "before", "again", "still",
    # Keep parity with Android's post-2026-08-05 protection. A missing common
    # word lets a profile term replace clear speech before any meaning guard.
    "cut", "cuts", "cutting", "turn", "turns", "turned", "turning",
    "play", "plays", "played", "playing", "push", "pushes", "pushed",
    "pull", "pulls", "pulled", "pick", "picks", "picked", "pay", "pays",
    "paid", "buy", "buys", "bought", "sell", "sells", "sold", "eat",
    "eats", "ate", "sit", "sits", "sat", "stand", "stands", "stood",
    "walk", "walks", "walked", "talk", "talks", "talked", "leave",
    "leaves", "left", "live", "lives", "lived", "feel", "feels", "felt",
    "hear", "hears", "heard", "wait", "waits", "waited", "watch",
    "watches", "watched", "open", "opens", "opened", "close", "closes",
    "closed", "guy", "guys", "man", "men", "way", "ways", "week", "weeks",
    "year", "years", "home", "house", "car", "cars", "phone", "meeting",
    "night", "tonight", "today", "tomorrow", "morning",
}


def _normalized_words(text):
    return " ".join(m.group(0).lower() for m in _WORD_RE.finditer(text or ""))


def _codes(text, encoder):
    try:
        encoded = encoder(text)
    except Exception:
        return set()
    if isinstance(encoded, str):
        encoded = (encoded,)
    return {
        re.sub(r"[^A-Z0-9]", "", str(code).upper())
        for code in (encoded or ())
        if code
    }


def _one_edit_or_less(left, right):
    """Return whether two short phonetic codes differ by at most one edit."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    i = j = edits = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(left) == len(right):
            i += 1
        j += 1
    if i < len(left) or j < len(right):
        edits += 1
    return edits <= 1


def _phonetic_relation(heard, probes, encoder, allow_approximate):
    heard_codes = _codes(heard, encoder)
    if not heard_codes:
        return None
    probe_codes = set()
    for probe in probes:
        probe_codes.update(_codes(probe, encoder))
    if not probe_codes:
        return None
    if heard_codes & probe_codes:
        return "phonetic"
    if not allow_approximate:
        return None
    for heard_code in heard_codes:
        for probe_code in probe_codes:
            if (
                len(heard_code) >= 3
                and len(probe_code) >= 3
                and heard_code[0] == probe_code[0]
                and heard_code[-1] == probe_code[-1]
                and _one_edit_or_less(heard_code, probe_code)
            ):
                return "approximate_phonetic"
    return None


def _is_low_confidence_phrase(heard, low_conf_texts):
    heard_norm = _normalized_words(heard)
    if not heard_norm:
        return False
    return any(
        heard_norm in _normalized_words(segment)
        for segment in (low_conf_texts or [])
        if segment
    )


def _is_distinctive_vocabulary(term):
    return (
        any(char.isupper() for char in term)
        or " " in term
        or any(not (char.isalnum() or char.isspace()) for char in term)
    )


def _replace_exact_corrections(text, corrections, matches):
    result = text
    for wrong, right in (corrections or {}).items():
        wrong = str(wrong or "").strip()
        right = str(right or "").strip()
        if not wrong or not right or wrong.lower() == right.lower():
            continue
        pattern = re.compile(
            r"(?<!\w)" + re.escape(wrong) + r"(?!\w)",
            re.IGNORECASE,
        )
        if pattern.search(result):
            matches.append({
                "heard": wrong,
                "term": right,
                "kind": "exact_correction",
            })
            result = pattern.sub(right, result)
    return result


def _replace_candidate(text, target, probes, kind, low_conf_texts, encoder):
    word_counts = sorted(
        {
            len(list(_WORD_RE.finditer(value)))
            for value in [target, *probes]
            if value
        },
        reverse=True,
    )
    tokens = list(_WORD_RE.finditer(text))
    replacements = []
    occupied = set()

    for count in word_counts:
        if count <= 0:
            continue
        for index in range(0, len(tokens) - count + 1):
            token_indexes = set(range(index, index + count))
            if occupied & token_indexes:
                continue
            start = tokens[index].start()
            end = tokens[index + count - 1].end()
            heard = text[start:end]
            heard_norm = _normalized_words(heard)
            if not heard_norm or heard_norm == _normalized_words(target):
                continue

            uncertain = _is_low_confidence_phrase(heard, low_conf_texts)
            if heard_norm in _APPROXIMATE_BLOCKLIST:
                continue
            if kind == "correction":
                if not uncertain:
                    continue
                relation = _phonetic_relation(
                    heard, probes, encoder, allow_approximate=True
                )
            else:
                if not (uncertain or _is_distinctive_vocabulary(target)):
                    continue
                relation = _phonetic_relation(
                    heard, probes, encoder, allow_approximate=False
                )
            if not relation:
                continue

            replacements.append((start, end, target, heard, relation))
            occupied.update(token_indexes)

    if not replacements:
        return text, []

    result = text
    applied = []
    for start, end, replacement, heard, relation in reversed(replacements):
        result = result[:start] + replacement + result[end:]
        applied.append({
            "heard": heard,
            "term": replacement,
            "kind": f"{kind}_{relation}",
        })
    applied.reverse()
    return result, applied


def apply_profile_terms(text, profile, low_conf_texts=None, encoder=None):
    """Return ``(corrected_text, matches)`` for Layer 3 profile terms.

    ``encoder`` is injectable so offline tests can exercise the matching rules
    even when the optional Metaphone package is absent.
    """
    if not text:
        return text, []
    profile = profile or {}
    matches = []
    result = _replace_exact_corrections(
        text, profile.get("corrections", {}), matches
    )
    encoder = encoder or _doublemetaphone
    if encoder is None:
        return result, matches

    candidates = []
    for wrong, right in (profile.get("corrections", {}) or {}).items():
        wrong = str(wrong or "").strip()
        right = str(right or "").strip()
        if wrong and right:
            candidates.append(("correction", right, [wrong, right]))
    for term in (profile.get("vocabulary", []) or []):
        term = str(term or "").strip()
        if term:
            candidates.append(("vocabulary", term, [term]))

    # Explicit corrections win ambiguous matches. Longer vocabulary phrases
    # run before shorter ones so "YOLO flag" is handled as one preferred term.
    candidates.sort(
        key=lambda item: (
            0 if item[0] == "correction" else 1,
            -len(list(_WORD_RE.finditer(item[1]))),
        )
    )
    seen_targets = set()
    for kind, target, probes in candidates:
        target_key = target.lower()
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        result, applied = _replace_candidate(
            result, target, probes, kind, low_conf_texts, encoder
        )
        matches.extend(applied)
    return result, matches
