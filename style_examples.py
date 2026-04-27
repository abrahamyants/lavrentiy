"""Persistent style-examples — (raw, accepted_output) pairs the user has
implicitly accepted by NOT hitting regenerate.

Mirror of WiM Android's StyleExamples.kt. Same state machine, same JSON
shape, same prompt-injection format. Stored as a JSON file at
<repo>/style_examples.json (parallel to lavrentiy.py).

State machine (handled in lavrentiy.reconstruct()):

  1. On reconstruct() call with previous_outputs non-empty:
       - Current call is a regenerate. Prior reconstruction was REJECTED.
       - rejection_store.record() captures the rejection.
       - Pending pair (if any) is the one being rejected — DROP it,
         do NOT promote to accepted.

  2. On reconstruct() call with previous_outputs empty:
       - Current call is fresh. Prior reconstruction was implicitly
         ACCEPTED (no regenerate fired before this).
       - Promote pending pair (if any) to style_examples.record().

  3. After reconstruction completes:
       - Set pending_pair = (raw_text, clean_text) so the NEXT call's
         verdict logic above can decide its fate.

False-negative: last reconstruction of a session never gets verdict'd
(no next call to promote it). Acceptable cost; v2 can persist on exit.

Storage: JSON file, capped at _MAX_ENTRIES (20). Atomic write via
.tmp+rename to survive engine crashes mid-save.

Privacy: all on-device. clear() exposed for "Erase voice memory" UI hook.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("lavrentiy.style_examples")

_STORE_PATH = Path(__file__).resolve().parent / "style_examples.json"
_MAX_ENTRIES = 20
_DEFAULT_RECENT_N = 5

# Pending pair: last reconstruction's (raw, output), awaiting accept-or-
# reject verdict on the next reconstruct() call.
pending_pair: Optional[Tuple[str, str]] = None


def _load() -> List[dict]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and "raw" in d and "output" in d]
        logger.warning("Style examples JSON wasn't a list, resetting")
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load style examples: %s", exc)
        return []


def _persist(items: List[dict]) -> None:
    try:
        tmp = _STORE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, _STORE_PATH)
    except OSError as exc:
        logger.warning("Failed to persist style examples: %s", exc)


def record(raw: str, output: str) -> None:
    """Append (raw, output) to the persistent history. No-op on blank
    or exact duplicate of most recent entry."""
    if not raw or not raw.strip() or not output or not output.strip():
        return
    items = _load()
    if items and items[-1].get("raw") == raw and items[-1].get("output") == output:
        return
    items.append({"raw": raw, "output": output})
    while len(items) > _MAX_ENTRIES:
        items.pop(0)
    _persist(items)
    logger.info(
        "Recorded accepted pair (raw='%s...') — total=%d",
        raw[:40], len(items)
    )


def recent(n: int = _DEFAULT_RECENT_N) -> List[dict]:
    """Most recent up-to-n examples, oldest first.
    Each item is a dict with 'raw' and 'output' keys."""
    items = _load()
    if len(items) <= n:
        return items
    return items[-n:]


def clear() -> None:
    """Erase all stored examples. UI hook for 'Erase voice memory' button."""
    try:
        if _STORE_PATH.exists():
            _STORE_PATH.unlink()
    except OSError as exc:
        logger.warning("Failed to clear style examples: %s", exc)
