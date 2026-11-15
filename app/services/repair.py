"""Answer repair.

Every other staleness tool stops at the diagnosis. Saphes closes the loop: once a
claim has an asserted value and a current value, the original answer can be
rewritten. This is the difference between a report and a fix, and it is the frame
people remember.
"""

from __future__ import annotations

from typing import Any, Iterable


def _variants(value: str) -> list[str]:
    """Spellings of a value that may appear in prose ("$20 / month", "20 per month")."""
    raw = value.strip()
    bare = raw.lstrip("vV")
    candidates = {
        raw,
        bare,
        raw.replace("/", " / "),
        bare.replace("/", " / "),
        raw.replace("/", " per "),
        bare.replace("/", " per "),
        raw.replace("/", " a "),
        bare.replace("/", " a "),
    }
    return sorted((c for c in candidates if c), key=len, reverse=True)


def repair_answer(answer: str, corrections: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Rewrite the answer so the stale values are the current ones.

    Only the values that were actually shown to have drifted are touched. If a
    value cannot be located in the text, it is skipped rather than guessed at.
    """
    updated = answer
    edits: list[dict[str, str]] = []

    for correction in corrections:
        asserted = (correction.get("asserted") or "").strip()
        current = (correction.get("current") or "").strip()
        if not asserted or not current:
            continue

        applied = False
        for variant in _variants(asserted):
            index = updated.lower().find(variant.lower())
            if index < 0:
                continue

            replacement = current
            # Keep the author's style: if the matched text was "3.9" and the
            # source says "v3.14", do not inject a "v" the answer never used.
            if variant[:1] not in {"v", "V"} and current[:1] in {"v", "V"}:
                replacement = current[1:]

            updated = f"{updated[:index]}{replacement}{updated[index + len(variant):]}"
            applied = True
            break

        if applied:
            edits.append({"asserted": asserted, "current": current})

    return {
        "corrected_answer": updated,
        "edits": edits,
        "changed": bool(edits),
    }
