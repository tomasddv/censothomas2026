"""Pure helpers for preserving manual census reviews across data refreshes."""

from copy import deepcopy
import math


def _manual_record(value):
    """Return a valid manual decision, or None for auto/invalid/empty state."""
    if not isinstance(value, dict) or value.get("src") == "auto":
        return None
    correction = value.get("corr")
    if correction is not None:
        if isinstance(correction, bool):
            return None
        try:
            correction = float(correction)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(correction) or correction < 0:
            return None
        return {"ok": False, "src": "manual", "corr": correction}
    if value.get("ok") is True:
        return {"ok": True, "src": "manual", "corr": None}
    return None


def restore_manual(base, saved):
    """Copy base and restore valid saved manual decisions, even over auto OK.

    Only IDs present in base are restored. Unknown IDs remain in the backing
    records file and are preserved by merge_review_records.
    """
    restored = deepcopy(base)
    if not isinstance(saved, dict):
        return restored
    for rid, value in saved.items():
        if rid not in restored:
            continue
        manual = _manual_record(value)
        if manual is not None:
            restored[rid] = manual
    return restored


def merge_review_records(existing, state, changed_ids=None):
    """Merge explicit local changes into the most recently read backing data.

    An explicit pending record (src=None, corr=None, ok=False) deletes its ID
    only when that ID is supplied in changed_ids. Auto and invalid records
    never overwrite persisted work. Omitting changed_ids upserts valid manual
    decisions only; it cannot infer deletions. Inputs are never mutated.

    The caller must provide concurrency control around reading and writing the
    remote file; this function does not make a remote read/write atomic.
    """
    merged = deepcopy(existing) if isinstance(existing, dict) else {}
    explicit = changed_ids is not None
    ids = state.keys() if changed_ids is None else changed_ids
    for rid in ids:
        if rid not in state:
            continue
        value = state[rid]
        manual = _manual_record(value)
        if manual is not None:
            merged[rid] = manual
        elif (
            explicit
            and isinstance(value, dict)
            and value.get("src") is None
            and value.get("corr") is None
            and value.get("ok") is False
        ):
            merged.pop(rid, None)
    return merged
