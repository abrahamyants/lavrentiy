"""
Full-matrix pipeline sweep — every layer, every tone, every situation, every mode.

WHY THIS EXISTS
---------------
Sixteen defects were fixed across wim-android and lavrentiy on 2026-08-02. Every
single one lived in deterministic code: regexes, guard predicates, loop
selection, prompt assembly, a constant, a pref key. None of them needed a live
model to reproduce. So the whole class is reachable offline, for free, in
seconds — which is what this file does.

It sweeps the configuration matrix and asserts invariants that must hold in
EVERY cell, rather than eyeballing output. The model is stubbed with scripted
candidate sequences so the retry loop and the meaning guard are exercised
deterministically.

Run: python test_pipeline_sweep.py
"""
import io
import itertools
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "wim", "api"))

import meaning_guard as MG          # noqa: E402
import prompt_builder as PB         # noqa: E402
import profile_terms as PT          # noqa: E402
import reconstruct as R             # noqa: E402

passed = 0
failures = []


def check(label, condition, detail=""):
    global passed
    if condition:
        passed += 1
    else:
        failures.append((label, detail))


# ── The matrix ──────────────────────────────────────────────────────
LAYERS = [1, 2, 3, 4]
TONES = ["formal", "professional", "casual", "friend"]
SITUATIONS = ["default", "high_stress", "reading"]
MODES = ["RAW", "FAST", "SAFE"]

PROFILE = {
    "vocabulary": ["Henderson", "synecdoche", "bake-off", "Kaminsky"],
    "corrections": {"Duncan": "Dankeschön", "Web3Forms": "WordPress"},
    "trigger_words": ["computer", "presentation"],
    "onset_weights": {"c": 0.82, "p": 0.61, "s": 0.44},
    "filler_words": ["um", "uh", "like"],
    "profile_l1": "russian",
}


# ── Corpus ──────────────────────────────────────────────────────────
# Two paragraphs of connected dictation, then targeted single utterances
# that each trip one specific guard. `anchors` must survive to the output;
# `forbidden` must never appear in it.

PARAGRAPH_ONE = (
    "so um I I I need you to send the the Henderson invoice before before friday "
    "and it's it's four thousand two hundred not not the twelve hundred one "
    "I mean the one from march third the co- founder signed it uh "
    "th- th- there's a pre- existing agreement in the file"
)

PARAGRAPH_TWO = (
    "no no that's not what I meant at all listen the m-m-meeting is at three pm "
    "I mean four pm on tuesday and I I can't help with the move this weekend "
    "I'm sorry about that but please confirm you got this thanks for watching "
    "the report is done can you send it"
)

CORPUS = [
    dict(name="paragraph_one", text=PARAGRAPH_ONE,
         # The compounds are ANCHORS, not artifacts — "co-" is not a prefix of
         # "founder", so it is a hyphenated word and must survive.
         anchors=["Henderson", "friday", "4200", "march",
                  "co- founder", "pre- existing"],
         forbidden=["c-c-", "th- th-"]),
    dict(name="paragraph_two", text=PARAGRAPH_TWO,
         anchors=["tuesday"],
         forbidden=["thanks for watching"]),

    dict(name="block_caption_hallucination",
         text="i need to call thanks for watching about the invoice",
         anchors=["invoice"], forbidden=["thanks for watching", "watching"]),
    dict(name="block_bracket_marker",
         text="tell him [BLANK_AUDIO] the meeting moved",
         anchors=["meeting"], forbidden=["[BLANK_AUDIO]", "["]),
    dict(name="emphatic_doubling",
         text="no no that is not what i meant", anchors=["no no"], forbidden=[]),
    dict(name="blocked_triple",
         text="i i i want to go to the store", anchors=["store"], forbidden=["i i i"]),
    dict(name="compound_hyphen",
         text="the co- founder signed the pre- existing agreement",
         anchors=["co- founder", "pre- existing"], forbidden=[]),
    dict(name="stutter_onset",
         text="c-c-can you s-s-send me the report by by friday",
         anchors=["friday", "report"], forbidden=["c-c-", "s-s-"]),
    dict(name="money_anchor",
         text="wire four thousand two hundred to henderson before monday",
         anchors=["4200", "henderson", "monday"], forbidden=[]),
    dict(name="digits_anchor",
         text="transfer $1,200 and 90% of the balance today",
         anchors=["1200", "90"], forbidden=[]),
    dict(name="self_correction_with_replacement",
         text="the meeting is at 3 pm i mean 4 pm on tuesday",
         anchors=["4", "tuesday"], forbidden=[]),
    dict(name="self_correction_without_replacement",
         text="wire 4200 to henderson i mean before monday",
         anchors=["4200", "henderson"], forbidden=[]),
    dict(name="negation",
         text="i i do not want to to cancel the appointment",
         anchors=["not", "cancel"], forbidden=[]),
    dict(name="apology_is_the_speakers_own",
         text="i am sorry i will be late for the meeting",
         anchors=["sorry", "meeting"], forbidden=[]),
    dict(name="prolongation",
         text="mmmmaybe we should just leave it yessss",
         anchors=["leave"], forbidden=["mmmm", "yessss"]),
    dict(name="natural_repeat_bye",
         text="bye bye see you tomorrow", anchors=["bye bye"], forbidden=[]),
    dict(name="fluent_input",
         text="please send me the report tomorrow",
         anchors=["report", "tomorrow"], forbidden=[]),
    dict(name="titles_and_names",
         text="tell d-d-doctor williams my son m-m-michael has an appointment on the the fifteenth",
         anchors=["williams", "michael", "fifteenth"], forbidden=["d-d-", "m-m-"]),
    dict(name="multi_sentence_question_last",
         text="the report is done can you send it", anchors=["report"], forbidden=[]),
    dict(name="single_word", text="stop", anchors=["stop"], forbidden=[]),
    dict(name="only_filler", text="um uh er", anchors=[], forbidden=[]),
]


def clean_stage(text):
    """The deterministic text path every layer runs before anything else."""
    return R.strip_disfluencies(R.strip_caption_artifacts(text))


# ════════════════════════════════════════════════════════════════════
print("\n=== SWEEP A: prompt matrix — layer x tone x situation x language ===")
# 4 layers x 4 tones x 3 situations x 2 languages = 96 prompts.
PLACEHOLDER = re.compile(r"\{[a-z_]+\}|None|\bnan\b")
combos = 0
for layer, tone, situation, lang in itertools.product(LAYERS, TONES, SITUATIONS, ["en", "es"]):
    combos += 1
    tag = f"L{layer}/{tone}/{situation}/{lang}"
    p = PB.build_prompt(PARAGRAPH_ONE, tone=tone, layer=layer, profile=PROFILE,
                        situation=situation, language_code=lang)
    check(f"{tag}: prompt is a non-trivial string", isinstance(p, str) and len(p) > 100, tag)
    check(f"{tag}: names its tone", tone in p.lower(), tag)
    check(f"{tag}: no unfilled placeholder", not PLACEHOLDER.search(p), tag)
    if layer >= 3:
        check(f"{tag}: L3+ carries profile vocabulary", "Henderson" in p, tag)
        check(f"{tag}: L3+ carries corrections", "Dankeschön" in p or "Duncan" in p, tag)
    if layer >= 4:
        check(f"{tag}: L4 carries clinical phoneme block", "HARDEST PHONEMES" in p, tag)
    if layer == 2:
        check(f"{tag}: L2 carries restate scaffolding", "ALWAYS RESTATE" in p, tag)
print(f"  {combos} prompt combinations built")

# Tone must actually change the prompt — the decorative-tile failure class.
for layer in LAYERS:
    prompts = {t: PB.build_prompt(PARAGRAPH_ONE, tone=t, layer=layer, profile=PROFILE)
               for t in TONES}
    check(f"L{layer}: all four tones produce distinct prompts",
          len(set(prompts.values())) == 4,
          f"distinct={len(set(prompts.values()))}/4")

# Situation severity must actually reach the prompt.
for layer in LAYERS:
    sev = {s: PB.build_prompt(PARAGRAPH_ONE, tone="casual", layer=layer,
                              profile=PROFILE, situation=s) for s in SITUATIONS}
    check(f"L{layer}: situations produce distinct prompts",
          len(set(sev.values())) == len(SITUATIONS),
          f"distinct={len(set(sev.values()))}/{len(SITUATIONS)}")

check("reading severity is the canonical 0.3",
      PB.SITUATION_SEVERITY["reading"] == 0.3, str(PB.SITUATION_SEVERITY))


# ════════════════════════════════════════════════════════════════════
print("=== SWEEP B: deterministic text stages over the corpus ===")
for case in CORPUS:
    name, text = case["name"], case["text"]
    out = clean_stage(text)

    check(f"{name}: non-empty output", bool(out.strip()), repr(out))
    check(f"{name}: idempotent", clean_stage(out) == out,
          f"{out!r} -> {clean_stage(out)!r}")
    for bad in case["forbidden"]:
        check(f"{name}: drops {bad!r}", bad.lower() not in out.lower(), repr(out))
    for anchor in case["anchors"]:
        if anchor.isdigit():
            check(f"{name}: keeps numeric anchor {anchor}",
                  int(anchor) in MG.numeric_values(out), repr(out))
        else:
            check(f"{name}: keeps anchor {anchor!r}",
                  anchor.lower() in out.lower(), repr(out))
print(f"  {len(CORPUS)} corpus cases through the deterministic path")

# Profile-term recovery must not destroy anchors at any layer.
for case in CORPUS:
    recovered, _ = PT.apply_profile_terms(case["text"], PROFILE)
    check(f"{case['name']}: profile terms keep it non-empty", bool(recovered.strip()))


# ════════════════════════════════════════════════════════════════════
print("=== SWEEP C: rewrite loop under a stubbed model, across the matrix ===")
CLEAN_G = {"lost": [], "invented": []}
LOST_G = {"lost": ["friday"], "invented": []}

SCENARIOS = [
    # name, scripted candidates, scripted guard verdicts, expected outcome
    ("accepts_good_first_try",
     ["Send the Henderson invoice by Friday."], [CLEAN_G], "accepted"),
    ("retries_identity_then_accepts",
     ["send the report", "Please send the report over today."], [CLEAN_G, CLEAN_G], "accepted"),
    ("retries_empty_then_accepts",
     ["", "Please send the report over today."], [CLEAN_G, CLEAN_G], "accepted"),
    ("exhausts_but_keeps_the_safe_attempt",
     ["send the report", "Send it.", "Send that."], [CLEAN_G, LOST_G, LOST_G], "safe_kept"),
    ("exhausts_with_nothing_safe",
     ["Send it.", "Send that.", "Send this."], [LOST_G, LOST_G, LOST_G], "hard_fail"),
]

raw = "send the report to henderson by friday"
for (scen, outs, guards, expect), layer, tone in itertools.product(SCENARIOS, LAYERS, TONES):
    calls = {"n": 0}

    def rewrite_once(messages, i, _outs=outs, _c=calls):
        _c["n"] += 1
        return _outs[i] if i < len(_outs) else _outs[-1]

    def guard_once(text, _g=guards, _c=calls):
        i = _c["n"] - 1
        return _g[i] if i < len(_g) else _g[-1]

    clean, attempts, gres = PB.run_layer2_rewrite(raw, [], rewrite_once, guard_once)
    tag = f"{scen}/L{layer}/{tone}"

    check(f"{tag}: returns a string", isinstance(clean, str), repr(clean))
    check(f"{tag}: attempts within bounds", 1 <= attempts <= PB.L2_MAX_REWRITE_ATTEMPTS, attempts)

    if expect == "accepted":
        check(f"{tag}: no anchors lost", not gres.get("lost"), str(gres))
        check(f"{tag}: output non-empty", bool(clean.strip()), repr(clean))
    elif expect == "safe_kept":
        check(f"{tag}: keeps the anchor-clean earlier attempt", clean == "send the report",
              repr(clean))
        check(f"{tag}: reports no lost anchors", not gres.get("lost"), str(gres))
    elif expect == "hard_fail":
        check(f"{tag}: surfaces the lost anchor so the caller can fall back",
              bool(gres.get("lost")), str(gres))
print(f"  {len(SCENARIOS) * len(LAYERS) * len(TONES)} loop runs")


# ════════════════════════════════════════════════════════════════════
print("=== SWEEP D: meaning guard on engineered raw/clean pairs ===")
GUARD_CASES = [
    ("keeps_correct_reformatting",
     "wire four thousand two hundred to henderson before monday",
     "Wire $4,200 to Henderson before Monday.", True),
    ("catches_a_changed_amount",
     "wire four thousand two hundred to henderson before monday",
     "Wire $1,200 to Henderson before Monday.", False),
    ("catches_a_dropped_date",
     "send the report to henderson by friday",
     "Send the report to Henderson.", False),
    ("allows_a_faithful_rewrite",
     "i i do not want to to cancel the appointment",
     "I do not want to cancel the appointment.", True),
    ("catches_dropped_negation",
     "i do not want to cancel the appointment",
     "I want to cancel the appointment.", False),

    # Spelled-out figures. CRITICAL_TOKEN_RE matches digits only, so an output
    # that kept the number in words produced no matches and every change passed.
    # L4 writes prose and spells figures out routinely.
    ("catches_a_spelled_out_amount_change",
     "wire four thousand two hundred to henderson",
     "Wire five thousand three hundred to Henderson.", False),
    ("catches_a_spelled_out_amount_shrinking",
     "wire four thousand two hundred to henderson",
     "Wire four thousand to Henderson.", False),
    ("catches_billion_swapped_for_million",
     "wire two billion to henderson", "Wire two million to Henderson.", False),
    ("catches_a_spelled_out_count_change",
     "send twenty copies", "Send thirty copies.", False),
    ("catches_digits_rewritten_as_the_wrong_words",
     "wire 4200 to henderson", "Wire one thousand two hundred to Henderson.", False),

    # The mirror direction: numeric anchors compared as literal substrings meant
    # a CORRECT reconstruction that spelled the figure out read as a lost anchor
    # and the whole reconstruction was thrown away.
    ("digits_spelled_out_is_not_a_loss",
     "wire 4200 to henderson", "Wire four thousand two hundred to Henderson.", True),
    ("comma_formatting_is_not_a_loss",
     "transfer $1,000 today", "Transfer 1000 today.", True),
    ("digits_to_words_is_not_a_loss",
     "send 5 copies", "Send five copies to the second floor.", True),
    ("words_to_digits_is_not_a_loss",
     "the meeting is at three pm on tuesday", "The meeting is at 3 PM on Tuesday.", True),
]
for name, rawt, cleant, should_pass in GUARD_CASES:
    g = MG.guard(rawt, cleant, vocabulary=PROFILE["vocabulary"])
    check(f"guard/{name}", g["ok"] is should_pass,
          f"ok={g['ok']} lost={g.get('lost')} invented={g.get('invented')}")

# Confidence must stay in range for every layer and both guard verdicts.
for layer, ok in itertools.product(LAYERS, [True, False]):
    gamma = R.compute_confidence(PARAGRAPH_ONE, clean_stage(PARAGRAPH_ONE), ok, layer)
    check(f"confidence in range L{layer}/falcon={ok}", 0.0 <= gamma <= 1.0, gamma)


# ════════════════════════════════════════════════════════════════════
# SWEEP E: cross-implementation parity, by EXTRACTION rather than by copy.
#
# The single most common defect shape in this codebase is a rule that exists in
# one implementation and not the other, or that got fixed on one side only. Five
# of the sixteen fixes on 2026-08-02 were that, including four introduced the
# same day by fixing Kotlin and forgetting Python.
#
# A hand-maintained second copy of the Kotlin patterns would rot exactly the way
# the originals did. So these are read out of DisfluencyFilter.kt and
# ReconstructClient.kt at test time and compared against the live Python ones.
# When the two drift, this fails.
# ════════════════════════════════════════════════════════════════════
print("=== SWEEP E: Kotlin <-> Python parity, extracted from source ===")

_ENV_ANDROID = os.environ.get("WIM_ANDROID_DIR")
# The env var is validated, not trusted: pointing it at a path that does not
# exist used to sail past this and crash on the first open() instead of
# reporting a clean failure.
ANDROID = _ENV_ANDROID if (_ENV_ANDROID and os.path.isdir(_ENV_ANDROID)) else next(
    (c for c in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wim-android"),
        "/root/wim-android",
    ) if os.path.isdir(c)), None)


def kt_raw_strings(src, name):
    """Concatenated \"\"\"...\"\"\" chunks of `private val NAME = Regex(...)`."""
    i = src.index(f"val {name} = Regex(")
    depth, j = 0, src.index("(", i)
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    body = src[j:k]
    return "".join(re.findall(r'"""(.*?)"""', body, re.S))


def kt_set(src, name):
    i = src.index(f"{name} = setOf(")
    depth, j = 0, src.index("(", i)
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    # String-shaped examples inside // comments are documentation, not members.
    # `Git` and `Git me off` in ProfileTermRecovery's incident note were being
    # counted as blocklist entries and made the parity check demand fake data.
    body = re.sub(r"//.*", "", src[j:k])
    return set(re.findall(r'"([^"]+)"', body))


def kt_map(src, name):
    i = src.index(f"val {name} = mapOf(")
    depth, j = 0, src.index("(", i)
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    return {m[0]: float(m[1]) for m in
            re.findall(r'"([a-z_]+)"\s+to\s+([0-9.]+)', src[j:k])}


def kt_regex_body(src, name):
    """Raw-string body of `val NAME = Regex(...)`, tolerating a line break
    between the `=` and the `Regex(` call."""
    i = src.index(f"val {name}")
    j = src.index("Regex(", i) + len("Regex")
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    return "".join(re.findall(r'"""(.*?)"""', src[j:k], re.S))


def py_regex_body(src, name):
    """Concatenated string parts of `NAME = re.compile(...)`, paren-balanced so
    the next declaration cannot bleed in."""
    m = re.search(rf"^{name}\s*=\s*re\.compile\(", src, re.M)
    j = m.end() - 1
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    # Both quote styles: meaning_guard.py mixes r'...' and r"..." across
    # declarations, and reading only one style silently yields an empty body —
    # which reads as a divergence when the patterns are in fact identical.
    return "".join(part for _, part in
                   re.findall(r"""r?("|')((?:(?!\1).)*)\1""", src[j:k], re.S))


def norm_pattern(x):
    """Whitespace, inline-flag and quantifier-spelling differences are noise."""
    return (re.sub(r"\s+", "", x)
            .replace("(?i)", "")
            .replace("{1,}", "+"))

def py_set_named(src, name):
    i = src.index(f"{name} = {{")
    j = src.index("\n}", i)
    return (set(re.findall(r'"([^"]+)"', src[i:j]))
            | set(re.findall(r"'([^']+)'", src[i:j])))


def py_map_named(src, name):
    i = src.index(f"{name} = {{")
    j = src.index("\n}", i)
    return {m[0]: int(m[1].replace("_", ""))
            for m in re.findall(r'"(\w+)":\s*([\d_]+)', src[i:j])}


def kt_map_long(src, name):
    i = src.index(f"val {name} = mapOf(")
    depth, j = 0, src.index("(", i)
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                break
    return {m[0]: int(m[1].replace("_", ""))
            for m in re.findall(r'"(\w+)"\s+to\s+([\d_]+)L?', src[j:k])}


if ANDROID is None:
    print("  SKIPPED — wim-android not found. Set WIM_ANDROID_DIR to run parity.")
    check("parity sweep ran", False, "wim-android checkout not located")
else:
    df = open(os.path.join(ANDROID, "app/src/main/java/com/wim/app/DisfluencyFilter.kt"),
              encoding="utf-8").read()
    rc = open(os.path.join(ANDROID, "app/src/main/java/com/wim/app/ReconstructClient.kt"),
              encoding="utf-8").read()

    # ── constants ──
    check("TONE_TEMP matches ReconstructClient.TONE_TEMPERATURE",
          kt_map(rc, "TONE_TEMPERATURE") == PB.TONE_TEMP,
          f"kt={kt_map(rc, 'TONE_TEMPERATURE')} py={PB.TONE_TEMP}")
    check("SITUATION_SEVERITY matches across implementations",
          kt_map(rc, "SITUATION_SEVERITY") == PB.SITUATION_SEVERITY,
          f"kt={kt_map(rc, 'SITUATION_SEVERITY')} py={PB.SITUATION_SEVERITY}")
    check("NATURAL_REPEATS matches across implementations",
          kt_set(df, "NATURAL_REPEATS") == R.NATURAL_REPEATS,
          f"kt-only={sorted(kt_set(df, 'NATURAL_REPEATS') - R.NATURAL_REPEATS)} "
          f"py-only={sorted(R.NATURAL_REPEATS - kt_set(df, 'NATURAL_REPEATS'))}")

    # ── per-stage behavioural parity on the corpus ──
    KT = {n: kt_raw_strings(df, n) for n in
          ("STUTTER_FRAGMENT", "STUTTER_FRAGMENT_NOSPACE", "PROLONGATION",
           "CAPTION_ARTIFACT", "SYSTEM_MARKER")}

    kt_frag = re.compile(KT["STUTTER_FRAGMENT"], re.I)
    kt_nospace = re.compile(KT["STUTTER_FRAGMENT_NOSPACE"], re.I)
    kt_prolong = re.compile(KT["PROLONGATION"], re.I)
    kt_caption = re.compile(KT["CAPTION_ARTIFACT"])
    kt_marker = re.compile(KT["SYSTEM_MARKER"])

    def kt_frag_stage(t):
        t = kt_frag.sub(lambda m: m.group(3)
                        if m.group(3).lower().startswith(m.group(1).lower())
                        else m.group(0), t)
        return kt_nospace.sub("", t)

    def py_frag_stage(t):
        t = re.sub(r"(\b\w+)-\s+((?:\1-\s+)*)(\w+)",
                   lambda m: m.group(3)
                   if m.group(3).lower().startswith(m.group(1).lower())
                   else m.group(0), t, flags=re.I)
        return re.sub(r"(\b\w+)-(?:\1-){1,40}", "", t, flags=re.I)

    for case in CORPUS:
        t = case["text"]
        check(f"parity/fragments/{case['name']}",
              kt_frag_stage(t) == py_frag_stage(t),
              f"kt={kt_frag_stage(t)!r} py={py_frag_stage(t)!r}")
        check(f"parity/prolongation/{case['name']}",
              kt_prolong.sub(lambda m: m.group(1), t) ==
              re.sub(r"([A-Za-z\u0400-\u04FF])\1{2,200}", r"\1", t),
              f"kt={kt_prolong.sub(lambda m: m.group(1), t)!r}")
        kt_clean = kt_marker.sub("", t)
        kt_clean = re.sub(r"\s{2,}", " ", kt_caption.sub(" ", kt_clean)).strip()
        kt_clean = kt_clean if kt_clean else t
        check(f"parity/captions/{case['name']}",
              kt_clean == R.strip_caption_artifacts(t),
              f"kt={kt_clean!r} py={R.strip_caption_artifacts(t)!r}")

    # ── the ONE divergence we know about, pinned so it cannot drift silently ──
    kt_word_repeat = kt_raw_strings(df, "WORD_REPEAT")
    check("word-repeat threshold divergence is still exactly as documented",
          "{1,40}" in kt_word_repeat,
          f"kt WORD_REPEAT={kt_word_repeat!r}")
    check("Python word-repeat still fires at 3+ only",
          R.strip_disfluencies("the the meeting").lower().count("the") == 2,
          R.strip_disfluencies("the the meeting"))
    check("Kotlin word-repeat still fires at 2+",
          re.search(kt_word_repeat, "the the meeting", re.I) is not None)
    # ── guard twins: regex bodies and the recovery blocklist ──
    mg_kt = open(os.path.join(ANDROID, "app/src/main/java/com/wim/app/MeaningGuard.kt"),
                 encoding="utf-8").read()
    mg_py = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "wim", "api", "meaning_guard.py"), encoding="utf-8").read()
    for rx in ("NEGATION_RE", "DATE_WORD_RE", "TITLE_RE", "NUMBER_WORD_RE",
               "HALLUCINATION_ARTIFACT_RE", "PROPER_NOUN_RE", "CRITICAL_TOKEN_RE"):
        a, b = kt_regex_body(mg_kt, rx), py_regex_body(mg_py, rx)
        check(f"parity/regex/{rx}", norm_pattern(a) == norm_pattern(b),
              f"kt={a[:110]!r} py={b[:110]!r}")

    check("parity/MeaningGuard.FUNCTION_WORDS",
          kt_set(mg_kt, "FUNCTION_WORDS") == py_set_named(mg_py, "_FUNCTION_WORDS"))
    check("parity/MeaningGuard.PROPER_NOUN_EXCLUDE",
          kt_set(mg_kt, "PROPER_NOUN_EXCLUDE") == py_set_named(mg_py, "PROPER_NOUN_EXCLUDE"))

    # Scale words understood, wherever each implementation keeps them. Kotlin
    # holds "hundred" in SCALES; Python special-cases it in the accumulator, so
    # comparing the raw maps would report a difference that is not one.
    kt_scale_words = set(kt_map_long(mg_kt, "SCALES")) | set(kt_map_long(mg_kt, "UNITS"))
    py_scale_words = (set(py_map_named(mg_py, "_NUMBER_SCALES"))
                      | set(py_map_named(mg_py, "_NUMBER_UNITS")) | {"hundred"})
    check("parity/number words understood by both",
          kt_scale_words == py_scale_words,
          f"kt-only={sorted(kt_scale_words - py_scale_words)} "
          f"py-only={sorted(py_scale_words - kt_scale_words)}")

    pt_kt = open(os.path.join(ANDROID, "app/src/main/java/com/wim/app/ProfileTermRecovery.kt"),
                 encoding="utf-8").read()
    pt_py = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "wim", "api", "profile_terms.py"), encoding="utf-8").read()
    kt_block = {t for t in kt_set(pt_kt, "APPROXIMATE_BLOCKLIST") if len(t.split()) < 4}
    check("parity/ProfileTermRecovery blocklist",
          kt_block == py_set_named(pt_py, "_APPROXIMATE_BLOCKLIST"),
          f"kt={len(kt_block)} py={len(py_set_named(pt_py, '_APPROXIMATE_BLOCKLIST'))}")

    print("  parity checked against", ANDROID)



# ════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"  PASSED: {passed}")
print(f"  FAILED: {len(failures)}")
print("=" * 60)
if failures:
    print("\nFAILURES:")
    for label, detail in failures[:40]:
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")
    if len(failures) > 40:
        print(f"  … and {len(failures) - 40} more")
sys.exit(1 if failures else 0)
