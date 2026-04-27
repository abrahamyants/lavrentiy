"""Domain-specific vocabulary packs (legal, medical, finance, hipaa, sf_pro).

Mirror of WiM Android's DomainPackHelper.kt — same JSON files (copied
verbatim from wim-android/app/src/main/assets/domain_packs/), same
prompt-injection format. The active pack is selected by the user's
profile_industry pref (set in the Profile screen) and appended to the
L2/L3 reconstruction prompt. Two effects:

  1. Vocabulary list — model preserves canonical spellings exactly
     (MRR/EBITDA/voir dire/HIPAA/etc.) instead of leaving them
     however the ASR garbled them.
  2. Phonetic-alias table — model silently corrects common ASR
     mishearings ("mom" → "MoM", "evita" → "EBITDA", "voir deer"
     → "voir dire", etc.).

Pack JSON files live at <repo>/domain_packs/<key>.json. Activated by
profile_industry → industry_to_pack_key mapping. Industries without a
built pack (trades, food, education, other, "") fall through to no
injection. Default = no pack.

Why JSON not hardcoded: vocab packs are content, not code. Editing a
JSON to add terms doesn't require a rebuild and lets non-coders
contribute domain expertise.

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

logger = logging.getLogger("lavrentiy.domain_pack")

_PACK_DIR = Path(__file__).resolve().parent / "domain_packs"
_CACHE: dict[str, Optional["Pack"]] = {}

BUILTIN_KEYS = ("general", "sf_pro", "legal", "medical", "finance", "hipaa")


@dataclass(frozen=True)
class Pack:
    key: str
    name: str
    prompt_note: str
    vocab: tuple[str, ...]
    phonetic_aliases: dict  # JSON-order preserving; small enough that immutability isn't load-bearing


def industry_to_pack_key(industry: str) -> str:
    """Map profile_industry → pack key. Mirrors WiM
    DomainPackHelper.industryToPackKey()."""
    if industry == "finance":
        return "finance"
    if industry == "legal":
        return "legal"
    if industry == "medical":
        return "medical"
    if industry in ("tech", "sales"):
        return "sf_pro"
    return "general"


def load_pack(key: str) -> Optional[Pack]:
    """Load and parse the pack JSON. Returns None for "general" or any
    missing/malformed pack. Cached per process."""
    if not key or key == "general":
        return None
    if key in _CACHE:
        return _CACHE[key]
    path = _PACK_DIR / f"{key}.json"
    if not path.exists():
        logger.warning("Domain pack not found: %s", path)
        _CACHE[key] = None
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pack = Pack(
            key=key,
            name=data.get("name", key),
            prompt_note=data.get("prompt_note", ""),
            vocab=tuple(data.get("vocab", [])),
            phonetic_aliases=dict(data.get("phonetic_aliases", {})),
        )
        _CACHE[key] = pack
        return pack
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load domain pack %s: %s", key, exc)
        _CACHE[key] = None
        return None


def active_pack(prof: dict) -> Optional[Pack]:
    """The pack matching the profile's industry, or None if unset / unmapped.

    Reads `profile_industry` first (matches WiM's `profile_*` pref convention),
    falls back to legacy `industry` for back-compat.
    """
    p = prof or {}
    industry = p.get("profile_industry") or p.get("industry") or ""
    key = industry_to_pack_key(industry)
    return load_pack(key)


def prompt_injection(prof: dict) -> str:
    """Build the domain-pack prompt block to append at L2/L3.

    Returns empty string when no pack is active so callers can append
    unconditionally. Format mirrors DomainPackHelper.promptInjection in
    WiM — same framing, vocab listing, and phonetic-alias table format,
    so the model sees an identical instruction whether it runs through
    Lavrentiy or WiM.
    """
    pack = active_pack(prof)
    if pack is None:
        return ""
    parts = [f"\n\n{pack.prompt_note}"]
    if pack.vocab:
        parts.append(
            "\nDomain vocabulary (canonical spellings — preserve exactly): "
            + ", ".join(pack.vocab)
        )
    if pack.phonetic_aliases:
        parts.append(
            "\nCRITICAL CANONICAL FORMS — these spelled-out words ARE the "
            "canonical acronyms/terms in this domain. Replace the lowercase/"
            "spelled-out form with the canonical form EVERY TIME, regardless "
            "of how the speaker pronounced them. NEVER expand the canonical "
            "form back to its long version unless the speaker explicitly "
            "said the long version."
        )
        for wrong, right in pack.phonetic_aliases.items():
            parts.append(f'\n  \u2022 "{wrong}" \u2192 "{right}" (do NOT expand "{right}" to its long form)')
    return "".join(parts)
