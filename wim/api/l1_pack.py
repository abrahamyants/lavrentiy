"""L1-transfer packs for non-native English speakers.

Phonetic accent disappears at the ASR layer (Whisper outputs text, no
audio). Syntactic, morphological, lexical, and discourse-pragmatic
patterns from the speaker's first language SURVIVE in the transcript.
Russian-L1 speakers drop articles. Mandarin-L1 speakers drop tense
markers. Spanish-L1 speakers calque idioms. These patterns are
deterministic enough that text-only normalization is reliable.

Pack JSON files live at <repo>/l1_packs/<language>.json. Activated by
the profile's `l1` field. Default = unset / "en" (no pack injected).

Mirrors WiM Android's L1PackHelper.kt — same Pack/Marker shape, same
prompt-injection format. Same JSON files; different load path.

Injection point: lavrentiy.reconstruct() at L2/L3 only. NOT L4 (the
clinical disfluency prompt has its own framing; double-instruction
harms output quality).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lavrentiy.l1_pack")

_PACK_DIR = Path(__file__).resolve().parent / "l1_packs"
_CACHE: dict[str, Optional["Pack"]] = {}

LANG_DISPLAY_NAMES = {
    "russian": "Russian",
    "spanish": "Spanish",
    "mandarin": "Mandarin Chinese",
    "hindi": "Hindi (Indian English)",
    "arabic": "Arabic",
    "farsi": "Farsi / Persian",
    "french": "French",
    "german": "German",
    "korean": "Korean",
    "japanese": "Japanese",
}

BUILTIN_KEYS = [
    "en",
    "russian", "spanish", "mandarin",
    "hindi", "arabic", "farsi", "french", "german", "korean", "japanese",
]


@dataclass(frozen=True)
class Example:
    input: str
    output: str


@dataclass(frozen=True)
class Marker:
    id: str
    category: str
    mechanism: str
    examples: tuple[Example, ...]
    prompt_hint: str
    citation: str


@dataclass(frozen=True)
class Pack:
    language: str
    markers: tuple[Marker, ...]
    notes: Optional[str] = None


def load_pack(language: str) -> Optional[Pack]:
    """Load and parse the pack JSON for `language`. Returns None for "en"
    or any missing/malformed pack. Cached per process."""
    if not language or language == "en":
        return None
    if language in _CACHE:
        return _CACHE[language]
    path = _PACK_DIR / f"{language}.json"
    if not path.exists():
        logger.warning("L1 pack not found: %s", path)
        _CACHE[language] = None
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        markers = tuple(
            Marker(
                id=m["id"],
                category=m["category"],
                mechanism=m["mechanism"],
                examples=tuple(
                    Example(input=e.get("input", ""), output=e.get("output", ""))
                    for e in m.get("examples", [])
                ),
                prompt_hint=m["prompt_hint"],
                citation=m.get("citation", ""),
            )
            for m in data.get("markers", [])
        )
        pack = Pack(
            language=data["language"],
            markers=markers,
            notes=data.get("notes"),
        )
        _CACHE[language] = pack
        return pack
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("Failed to load L1 pack %s: %s", language, exc)
        _CACHE[language] = None
        return None


def active_pack(prof: dict) -> Optional[Pack]:
    """The pack matching the profile's L1 field, or None for native English.

    Reads `profile_l1` first (matches WiM's `profile_*` pref convention used
    for profile_industry etc.), falls back to legacy `l1` so existing
    Lavrentiy profiles keep working without migration.
    """
    p = prof or {}
    l1 = p.get("profile_l1") or p.get("l1") or ""
    return load_pack(l1)


def prompt_injection(prof: dict) -> str:
    """Build the L1 prompt block to inject at L2/L3.

    Returns empty string when no pack is active so callers can append
    unconditionally. Reads profile.accent_mode to pick framing:
        "polish" (default) — normalize patterns toward written-English
                             convention. For boss / clients / strangers.
        "keep"             — preserve patterns as authentic voice. Same
                             pack, opposite directive. For family / friends
                             / casual contexts. The Design Justice surface.

    Mirrors WiM Android's L1PackHelper.kt buildPolishInjection /
    buildKeepInjection — identical instruction structure both sides.
    """
    pack = active_pack(prof)
    if pack is None:
        return ""
    display = LANG_DISPLAY_NAMES.get(pack.language, pack.language.capitalize())
    # Top-level for Cloud Function path (WiM ReconstructClient flattens
    # the profile). Nested for local Lavrentiy path (profile has a
    # preferences sub-dict).
    p = prof or {}
    mode = p.get("accent_mode") or p.get("preferences", {}).get("accent_mode") or "polish"
    if mode == "keep":
        return _build_keep_injection(pack, display)
    return _build_polish_injection(pack, display)


def _build_polish_injection(pack: Pack, display: str) -> str:
    parts = [
        f"\n\nSPEAKER L1: {display}. Their English may show systematic L1-transfer "
        "patterns documented at the group level in second-language acquisition "
        "research — not random errors. When restating into written prose, "
        "normalize the patterns listed below. Preserve the speaker's word choice, "
        "slang, profanity, and intent.",
        "\n\nNORMALIZE these patterns:",
    ]
    for i, m in enumerate(pack.markers, start=1):
        line = f"\n{i}. {m.prompt_hint}"
        if m.examples:
            e = m.examples[0]
            if e.input and e.output:
                line += f' e.g. "{e.input}" → "{e.output}"'
        parts.append(line)
    parts.append(
        "\n\nThis is normalization toward written-English convention, not "
        "erasure of the speaker's voice. If a listed pattern appears as "
        "deliberate stylistic emphasis or intentional code-switching, preserve it."
    )
    return "".join(parts)


def _build_keep_injection(pack: Pack, display: str) -> str:
    parts = [
        f"\n\nSPEAKER L1: {display}. Their English carries systematic patterns "
        "from their first language — these are authentic features of how they "
        "speak, not errors. The speaker has explicitly chosen to PRESERVE their "
        "voice in this output.",
        "\n\nPRESERVE these patterns verbatim:",
    ]
    for i, m in enumerate(pack.markers, start=1):
        # First word of the prompt_hint is typically the imperative verb
        # (Insert / Add / Convert / Restore / Remove). Replace it with
        # "Keep" to flip the directive while reusing the marker phrasing.
        words = m.prompt_hint.split(" ", 1)
        rest = words[1] if len(words) > 1 else m.prompt_hint
        line = f"\n{i}. Keep {rest}"
        if m.examples:
            e = m.examples[0]
            if e.input:
                line += f' e.g. keep "{e.input}" as "{e.input}"'
        parts.append(line)
    parts.append(
        "\n\nFix only verbatim transcription errors (homophone confusions, "
        "mis-segmented words, missing punctuation that affects readability). "
        "Do NOT smooth syntax, do NOT insert articles the speaker didn't say, "
        "do NOT reorder for Standard English grammar. Render the speaker's "
        "voice as they spoke it."
    )
    return "".join(parts)
