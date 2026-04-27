"""Persistent rejection history — outputs the user has rejected across sessions.

Mirror of WiM Android's RejectionStore.kt. Same capture semantics, same
prompt-injection format. Stored as a JSON file at <repo>/rejection_history.json
(parallel to lavrentiy.py).

Used by lavrentiy.reconstruct() to inject a "patterns the user has rejected
in past sessions — avoid producing structurally similar text" block into the
L3+ reconstruction prompt. This is the cross-session, persistent counterpart
to the within-session regenerate-as-negative-example which fires off the
input-overlap heuristic in pipeline().

Capture: lavrentiy.reconstruct() calls record() whenever an incoming call
has non-empty previous_outputs — the last entry is the output that was
just rejected by the regenerate detection.

Use: lavrentiy.reconstruct() calls recent(n) at L3+ to pull up to 10
historical rejections to inject as negative few-shot examples.

Storage: capped at MAX_ENTRIES (30). Newest at the end. Deduplicates against
the most recent entry only — repeated regenerates of the same output are
common (user redoes 2-3 times before giving up) and we don't want to fill
the buffer with copies.

Privacy: all on-device. JSON file lives in the repo dir; under the install
this lands at engine/rejection_history.json. clear() exposed for a "Erase
voice memory" UI hook on the dashboard.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger("lavrentiy.rejection_store")

_STORE_PATH = Path(__file__).resolve().parent / "rejection_history.json"
_MAX_ENTRIES = 30
_DEFAULT_RECENT_N = 10


def _load() -> List[str]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x) for x in data]
        logger.warning("Rejection store JSON wasn't a list, resetting")
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load rejection store: %s", exc)
        return []


def _persist(items: List[str]) -> None:
    try:
        # Atomic-ish write: write to .tmp, rename. Avoids a corrupt half-
        # written file if the process dies mid-save (engine crash mid-recon).
        tmp = _STORE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, _STORE_PATH)
    except OSError as exc:
        logger.warning("Failed to persist rejection store: %s", exc)


def record(rejected: str) -> None:
    """Append `rejected` to the persistent history. No-op on empty input
    or duplicate of most recent entry."""
    if not rejected or not rejected.strip():
        return
    items = _load()
    if items and items[-1] == rejected:
        return  # repeated regenerate of the same output — skip
    items.append(rejected)
    while len(items) > _MAX_ENTRIES:
        items.pop(0)
    _persist(items)
    logger.info(
        "Recorded rejection (%s...) — total=%d",
        rejected[:40], len(items)
    )


def recent(n: int = _DEFAULT_RECENT_N) -> List[str]:
    """Most recent up-to-n rejections, oldest first."""
    items = _load()
    if len(items) <= n:
        return items
    return items[-n:]


def clear() -> None:
    """Erase all stored rejections. UI hook for 'Erase voice memory' button."""
    try:
        if _STORE_PATH.exists():
            _STORE_PATH.unlink()
    except OSError as exc:
        logger.warning("Failed to clear rejection store: %s", exc)
