"""Standalone test: extracts strip_disfluencies from eval-build and runs on known inputs.
No imports from lavrentiy.py's module-level code — just pastes the function + deps.
Deletes itself after running.
"""
import re

NATURAL_REPEATS = {
    "had had", "that that", "is is", "was was", "do do",
    "can can", "no no", "bye bye", "so so", "very very",
    "go go", "now now", "come come", "well well",
    "out out", "boo boo", "ha ha", "ho ho",
    "knock knock", "tsk tsk", "aye aye",
    "really really", "many many", "much much", "big big",
    "long long", "old old", "hot hot", "busy busy",
    "right right", "sure sure", "fine fine", "okay okay",
    "да да", "нет нет", "ну ну",
}

_ENGLISH_PREFIXES = {
    "re", "un", "pre", "de", "en", "in", "dis", "mis",
    "sub", "ex", "non", "pro", "anti", "co",
}

_STRIP_FILLERS = {
    "um", "uh", "uhm", "umm", "erm", "er", "ah", "hm", "hmm",
    "э", "ээ", "эм", "эээ", "ну", "нуу",
}


def strip_disfluencies(text):
    if not text or not text.strip():
        return text

    def _strip_stutter(m):
        frags = [f.strip() for f in m.group(1).strip().rstrip('-').split('-') if f.strip()]
        full_word = m.group(2)
        if not frags:
            return m.group(0)
        if len(frags) == 1 and frags[0].lower() in _ENGLISH_PREFIXES:
            return m.group(0)
        if full_word.lower().startswith(frags[0].lower()):
            return full_word
        return m.group(0)
    cleaned = re.sub(r'\b((?:\w{1,3}-\s*)+)(\w+)\b', _strip_stutter, text, flags=re.IGNORECASE)

    def _dedup_word(m):
        phrase = f"{m.group(1)} {m.group(1)}".lower()
        if phrase in NATURAL_REPEATS:
            return m.group(0)
        return m.group(1)
    cleaned = re.sub(r'\b(\w+)(?:\s+\1){1,}\b', _dedup_word, cleaned, flags=re.IGNORECASE)

    def _dedup_phrase(m):
        if m.group(1).lower() in NATURAL_REPEATS:
            return m.group(0)
        return m.group(1)
    cleaned = re.sub(r'\b(\w+\s+\w+(?:\s+\w+)?)\s+\1\b', _dedup_phrase, cleaned, flags=re.IGNORECASE)

    words = cleaned.split()
    filtered = []
    for i, w in enumerate(words):
        w_lower = w.lower().rstrip('.,!?;:')
        if w_lower in _STRIP_FILLERS:
            if len(words) == 1:
                filtered.append(w)
            continue
        filtered.append(w)

    result = " ".join(filtered).strip()
    result = re.sub(r'\s{2,}', ' ', result)
    return result if result else text


# ── Tests ──────────────────────────────────────────────────────
cases = [
    # (label, input, expected_substring_present_or_absent_markers)
    ("Input B (full)",
     "I I I w-w-want to to [Pause] s-schedule a m-m-m-meeting for for n-next Thursday to d-d-discuss the the [Laughter] ent-enterprise s-s-software.",
     None),
    ("bare I I I", "I I I want", "I want"),
    ("to to", "to to", "to"),
    ("w-w-want", "w-w-want", "want"),
    ("s-schedule", "s-schedule", "schedule"),
    ("m-m-m-meeting", "m-m-m-meeting", "meeting"),
    ("n-next", "n-next", "next"),
    ("ent-enterprise", "ent-enterprise", "enterprise"),
    ("d-d-discuss", "d-d-discuss", "discuss"),
    ("SAFE: state-of-the-art", "state-of-the-art", "state-of-the-art"),
    ("SAFE: well-known", "well-known", "well-known"),
    ("SAFE: twenty-one", "twenty-one", "twenty-one"),
    ("SAFE: e-mail", "e-mail", "e-mail"),
    ("SAFE: T-shirt", "T-shirt", "T-shirt"),
    ("SAFE: re-read (real prefix)", "re-read this", "re-read this"),
    ("SAFE: un-done (real prefix)", "un-done deal", "un-done deal"),
    ("EMPHASIS: no no", "no no don't", "no no don't"),
    ("EMPHASIS: really really", "I really really like it", "really really"),
    ("EMPHASIS: bye bye", "bye bye", "bye bye"),
]

print("=" * 80)
print(f"{'LABEL':<35} {'INPUT':<40} -> OUTPUT")
print("=" * 80)
all_pass = True
for label, inp, expected in cases:
    got = strip_disfluencies(inp)
    status = ""
    if expected is not None:
        if expected in got:
            status = "[PASS]"
        else:
            status = f"[FAIL expected '{expected}' in output]"
            all_pass = False
    print(f"{label:<35} {inp!r:<40}")
    print(f"  -> {got!r:<66} {status}")
print("=" * 80)
print("ALL PASS" if all_pass else "SOME FAILED")
