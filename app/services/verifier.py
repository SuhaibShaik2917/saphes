from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.config import OFFLINE_MODE
from app.models import ClaimVerdict
from app.services.claim_extractor import extract_claims
from app.services.evidence_service import deterministic_verdict, evaluate_claim
from app.services.external_adapters import extract_claims_via_bifrost
from app.services.repair import repair_answer

VOLATILITY_WEIGHT = {"high": 1.0, "medium": 0.65, "low": 0.35}
STALENESS_VALUE = {"stale": 1.0, "uncertain": 0.5, "current": 0.0}

RISK_LABEL = {1.0: "act now", 0.5: "cannot confirm", 0.0: "holds"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ms(start: float) -> int:
    return max(1, int((time.perf_counter() - start) * 1000))


def risk_score(verdict: ClaimVerdict) -> float:
    """Triage, not enumeration: a stale price outranks a stale footnote."""
    weight = VOLATILITY_WEIGHT.get(verdict.volatility, 0.5)
    staleness = STALENESS_VALUE.get(verdict.verdict, 0.5)
    return round(staleness * weight * (0.5 + verdict.confidence), 3)


def staleness_index(verdicts: list[ClaimVerdict]) -> float:
    """One number per answer: how much of it has drifted or cannot be confirmed."""
    if not verdicts:
        return 0.0

    total_weight = 0.0
    weighted = 0.0

    for item in verdicts:
        weight = VOLATILITY_WEIGHT.get(item.volatility, 0.5) * (0.5 + item.confidence)
        total_weight += weight
        weighted += weight * STALENESS_VALUE.get(item.verdict, 0.5)

    if total_weight <= 0:
        return 0.0
    return round(weighted / total_weight, 2)


def risk_band(index: float) -> str:
    if index < 0.25:
        return "low"
    if index < 0.55:
        return "moderate"
    return "high"


def _headline(counts: dict[str, int], total: int) -> str:
    if total == 0:
        return "Nothing to check."
    drifted = counts["stale"]
    unconfirmed = counts["uncertain"]
    if drifted and unconfirmed:
        return f"{drifted} of {total} claims have drifted; {unconfirmed} could not be confirmed."
    if drifted:
        return f"{drifted} of {total} claims have drifted since they were written."
    if unconfirmed:
        return f"{unconfirmed} of {total} claims could not be confirmed against live sources."
    return f"All {total} claims still hold against live sources."


def verify_answer(answer: str, allow_live: bool | None = None) -> dict[str, Any]:
    live = (not OFFLINE_MODE) if allow_live is None else allow_live
    trace: list[dict[str, Any]] = []

    started = time.perf_counter()
    normalized_claims = extract_claims_via_bifrost(answer)
    claims = extract_claims(answer)
    trace.append({"step": "split the answer into claims", "count": len(claims), "ms": _ms(started)})

    verdicts: list[ClaimVerdict] = []
    for claim in claims:
        try:
            verdicts.append(evaluate_claim(claim, allow_live=live))
        except Exception:  # one bad claim must never kill a response
            verdicts.append(deterministic_verdict(claim))
    trace.append({
        "step": "searched the live web",
        "count": sum(1 for item in verdicts if item.sources),
        "ms": sum(item.search_ms for item in verdicts),
    })
    trace.append({
        "step": "compared asserted values with evidence",
        "count": len(verdicts),
        "ms": sum(item.compare_ms for item in verdicts),
    })

    counts = {"current": 0, "stale": 0, "uncertain": 0}
    for item in verdicts:
        counts[item.verdict] += 1

    notes = [item.note for item in verdicts if item.note]
    evidence_note = notes[0] if notes else None

    modes = {item.evidence_mode for item in verdicts}
    if modes == {"live"}:
        evidence_mode = "live"
    elif modes == {"cached"}:
        evidence_mode = "cached"
    elif modes == {"heuristic"}:
        evidence_mode = "heuristic"
    elif modes:
        evidence_mode = "mixed"
    else:
        evidence_mode = "heuristic"

    index = staleness_index(verdicts)

    corrections = [
        {
            "claim": item.claim,
            "asserted": item.asserted_value,
            "current": item.current_value,
        }
        for item in verdicts
        if item.verdict == "stale" and item.asserted_value and item.current_value
    ]

    started = time.perf_counter()
    repair = repair_answer(answer, corrections)
    trace.append({"step": "repaired the answer", "count": len(repair["edits"]), "ms": _ms(started)})

    # Triage order: highest risk first. Judges (and users) read the top of the list.
    ordered = sorted(verdicts, key=risk_score, reverse=True)
    results: list[dict[str, Any]] = []
    for position, item in enumerate(ordered, start=1):
        payload = item.to_dict()
        score = risk_score(item)
        payload["priority"] = position
        payload["risk_score"] = score
        payload["risk_label"] = (
            "act now" if item.verdict == "stale"
            else "cannot confirm" if item.verdict == "uncertain"
            else "holds"
        )
        results.append(payload)

    return {
        "answer": answer,
        "checked_at": _now(),
        "evidence_mode": evidence_mode,
        "evidence_note": evidence_note,
        "claims_checked": len(verdicts),
        "staleness_index": index,
        "risk_band": risk_band(index),
        "headline": _headline(counts, len(verdicts)),
        "summary": counts,
        "corrections": corrections,
        "repair": repair,
        "trace": trace,
        "results": results,
    }
