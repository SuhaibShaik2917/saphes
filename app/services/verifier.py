from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.config import MAX_CLAIMS, OFFLINE_MODE
from app.models import Claim, ClaimVerdict
from app.services.claim_extractor import extract_claims
from app.services.evidence_service import deterministic_verdict, evaluate_claim
from app.services.external_adapters import extract_claims_via_bifrost
from app.services.ingest import IngestResult, extract_from_text
from app.services.repair import repair_answer

VOLATILITY_WEIGHT = {"high": 1.0, "medium": 0.65, "low": 0.35}
STALENESS_VALUE = {"stale": 1.0, "uncertain": 0.5, "current": 0.0, "non_factual": 0.0}

NON_FACTUAL_EXPLANATION = {
    "opinion": "This is an opinion or judgement, not a checkable factual claim, so no factual verdict is issued.",
    "prediction": "This is a prediction about the future, not an established fact, so no factual verdict is issued.",
    "question": "This is a question, not a claim, so there is nothing to verify.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def risk_score(verdict: ClaimVerdict) -> float:
    """Triage, not enumeration: a stale price outranks a stale footnote."""
    weight = VOLATILITY_WEIGHT.get(verdict.volatility, 0.5)
    staleness = STALENESS_VALUE.get(verdict.verdict, 0.5)
    return round(staleness * weight * (0.5 + verdict.confidence), 3)


def staleness_index(verdicts: list[ClaimVerdict]) -> float:
    """One number per answer: how much of it has drifted or cannot be confirmed."""
    checkable = [item for item in verdicts if item.verdict != "non_factual"]
    if not checkable:
        return 0.0

    total_weight = 0.0
    weighted = 0.0
    for item in checkable:
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
    checkable = counts["current"] + counts["stale"] + counts["uncertain"]
    if total == 0:
        return "Nothing readable to check."
    if checkable == 0:
        return f"No verifiable factual claims found in {total} statements."
    drifted, unconfirmed = counts["stale"], counts["uncertain"]
    if drifted and unconfirmed:
        return f"{drifted} of {checkable} checkable claims have drifted; {unconfirmed} could not be confirmed."
    if drifted:
        return f"{drifted} of {checkable} checkable claims have drifted since they were written."
    if unconfirmed:
        return f"{unconfirmed} of {checkable} checkable claims could not be confirmed against live sources."
    return f"All {checkable} checkable claims still hold against live sources."


def _non_factual_verdict(claim: Claim) -> ClaimVerdict:
    return ClaimVerdict(
        claim=claim.text,
        verdict="non_factual",
        explanation=NON_FACTUAL_EXPLANATION.get(claim.kind, "Not a verifiable factual claim."),
        confidence=0.0,
        volatility=claim.volatility,
        checked_at=_now(),
        sources=[],
        evidence_mode="none",  # type: ignore[arg-type]
        claim_type=claim.kind,
    )


def verify_answer(
    answer: str,
    allow_live: bool | None = None,
    ingest: IngestResult | None = None,
) -> dict[str, Any]:
    """Run the full pipeline. Stages are recorded so the response explains itself."""
    live = (not OFFLINE_MODE) if allow_live is None else allow_live
    stages: list[dict[str, Any]] = []

    # ---- stage 1: input ingestion -----------------------------------------
    started = time.perf_counter()
    source = ingest or extract_from_text(answer)
    limitations = list(source.limitations)
    stages.append({
        "stage": 1,
        "step": "input ingestion",
        "detail": f"detected {source.kind}",
        "count": 1,
        "ms": _ms(started),
    })

    # ---- stage 2: content extraction --------------------------------------
    started = time.perf_counter()
    text = source.text or ""
    stages.append({
        "stage": 2,
        "step": "content extraction",
        "detail": f"{len(text)} chars from {source.kind}",
        "count": len(text),
        "ms": _ms(started),
    })

    if not text.strip():
        for number, name in (
            (3, "normalise & detect claims"),
            (4, "plan verification"),
            (5, "retrieve evidence"),
            (6, "evaluate evidence"),
            (7, "assign verdicts & confidence"),
            (8, "assemble output"),
        ):
            stages.append({"stage": number, "step": name, "detail": "skipped - nothing to read",
                           "count": 0, "ms": 0})
        return {
            "answer": answer,
            "input_kind": source.kind,
            "source_ref": source.source_ref,
            "checked_at": _now(),
            "evidence_mode": "none",
            "evidence_note": None,
            "claims_checked": 0,
            "claims_truncated": False,
            "max_claims": MAX_CLAIMS,
            "staleness_index": 0.0,
            "risk_band": "low",
            "headline": "Nothing readable was extracted, so nothing was verified.",
            "summary": {"current": 0, "stale": 0, "uncertain": 0, "non_factual": 0},
            "corrections": [],
            "repair": {"corrected_answer": answer, "edits": [], "changed": False},
            # `trace` is kept as a backwards-compatible alias of `stages`.
            "trace": stages,
            "stages": stages,
            "limitations": limitations,
            "results": [],
        }

    # ---- stage 3: normalisation + claim detection --------------------------
    started = time.perf_counter()
    gateway_claims = extract_claims_via_bifrost(text)
    if gateway_claims:
        claims = [
            Claim(
                text=str(item.get("text", "")).strip(),
                volatility=item.get("volatility", "medium"),
                category=item.get("category", "general"),
                confidence=float(item.get("confidence", 0.7)),
                kind=item.get("kind", "fact"),
            )
            for item in gateway_claims
            if str(item.get("text", "")).strip()
        ] or extract_claims(text)
    else:
        claims = extract_claims(text)

    total_claims = len(claims)
    if total_claims > MAX_CLAIMS:
        claims = claims[:MAX_CLAIMS]
        limitations.append(
            f"Only the first {MAX_CLAIMS} of {total_claims} claims were checked; the rest were skipped."
        )
    stages.append({
        "stage": 3,
        "step": "normalise & detect claims",
        "detail": f"{sum(1 for c in claims if c.kind == 'fact')} factual, "
                  f"{sum(1 for c in claims if c.kind != 'fact')} non-factual",
        "count": len(claims),
        "ms": _ms(started),
    })

    if not claims:
        limitations.append("No statement in this input could be checked, so nothing was verified.")
        for number, name in (
            (4, "plan verification"),
            (5, "retrieve evidence"),
            (6, "evaluate evidence"),
            (7, "assign verdicts & confidence"),
            (8, "assemble output"),
        ):
            stages.append({"stage": number, "step": name, "detail": "skipped - nothing to check",
                           "count": 0, "ms": 0})
        return {
            "answer": answer,
            "input_kind": source.kind,
            "source_ref": source.source_ref,
            "checked_at": _now(),
            "evidence_mode": "none",
            "evidence_note": None,
            "claims_checked": 0,
            "claims_truncated": False,
            "max_claims": MAX_CLAIMS,
            "staleness_index": 0.0,
            "risk_band": "low",
            "headline": "No checkable statements were found in this input.",
            "summary": {"current": 0, "stale": 0, "uncertain": 0, "non_factual": 0},
            "corrections": [],
            "repair": {"corrected_answer": answer, "edits": [], "changed": False},
            "trace": stages,  # backwards-compatible alias of `stages`
            "stages": stages,
            "limitations": limitations,
            "results": [],
        }

    # ---- stage 4: verification planning -----------------------------------
    started = time.perf_counter()
    checkable = [claim for claim in claims if claim.kind == "fact"]
    stages.append({
        "stage": 4,
        "step": "plan verification",
        "detail": "live retrieval per factual claim" if (checkable and live) else
                  "no retrieval required" if not checkable else "retrieval disabled",
        "count": len(checkable),
        "ms": _ms(started),
    })

    # ---- stages 5 + 6: retrieval and evaluation ---------------------------
    started = time.perf_counter()
    verdicts: list[ClaimVerdict] = []
    for claim in claims:
        if claim.kind != "fact":
            verdicts.append(_non_factual_verdict(claim))
            continue
        try:
            verdicts.append(evaluate_claim(claim, allow_live=live))
        except Exception:
            verdicts.append(deterministic_verdict(claim))
    evaluate_ms = _ms(started)

    stages.append({
        "stage": 5,
        "step": "retrieve evidence",
        "detail": f"{sum(1 for v in verdicts if v.sources)} claims with sources",
        "count": sum(1 for v in verdicts if v.sources),
        "ms": sum(item.search_ms for item in verdicts),
    })
    stages.append({
        "stage": 6,
        "step": "evaluate evidence",
        "detail": "support / contradict / not established",
        "count": len(checkable),
        "ms": sum(item.compare_ms for item in verdicts) or evaluate_ms,
    })

    # ---- stage 7: verdict + confidence ------------------------------------
    started = time.perf_counter()
    counts = {"current": 0, "stale": 0, "uncertain": 0, "non_factual": 0}
    for item in verdicts:
        counts[item.verdict] += 1
    index = staleness_index(verdicts)
    stages.append({
        "stage": 7,
        "step": "assign verdicts & confidence",
        "detail": f"staleness index {index}",
        "count": len(verdicts),
        "ms": _ms(started),
    })

    notes = [item.note for item in verdicts if item.note]
    evidence_note = notes[0] if notes else None

    modes = {item.evidence_mode for item in verdicts if item.evidence_mode != "none"}
    if not modes:
        evidence_mode = "none"
    elif modes == {"live"}:
        evidence_mode = "live"
    elif modes == {"cached"}:
        evidence_mode = "cached"
    elif modes == {"heuristic"}:
        evidence_mode = "heuristic"
    else:
        evidence_mode = "mixed"

    corrections = [
        {"claim": item.claim, "asserted": item.asserted_value, "current": item.current_value}
        for item in verdicts
        if item.verdict == "stale" and item.asserted_value and item.current_value
    ]

    # ---- stage 8: final output -------------------------------------------
    started = time.perf_counter()
    repair = repair_answer(text, corrections)
    ordered = sorted(verdicts, key=risk_score, reverse=True)
    results: list[dict[str, Any]] = []
    for position, item in enumerate(ordered, start=1):
        payload = item.to_dict()
        payload["priority"] = position
        payload["risk_score"] = risk_score(item)
        payload["risk_label"] = (
            "act now" if item.verdict == "stale"
            else "cannot confirm" if item.verdict == "uncertain"
            else "not a factual claim" if item.verdict == "non_factual"
            else "holds"
        )
        results.append(payload)
    stages.append({
        "stage": 8,
        "step": "assemble output",
        "detail": f"{len(repair['edits'])} repairs",
        "count": len(results),
        "ms": _ms(started),
    })

    return {
        "answer": answer,
        "input_kind": source.kind,
        "source_ref": source.source_ref,
        "input_meta": source.meta,
        "checked_at": _now(),
        "evidence_mode": evidence_mode,
        "evidence_note": evidence_note,
        "claims_checked": len(verdicts),
        "claims_truncated": total_claims > MAX_CLAIMS,
        "max_claims": MAX_CLAIMS,
        "staleness_index": index,
        "risk_band": risk_band(index),
        "headline": _headline(counts, len(verdicts)),
        "summary": counts,
        "corrections": corrections,
        "repair": repair,
        "trace": stages,  # backwards-compatible alias of `stages`
        "stages": stages,
        "limitations": limitations,
        "results": results,
    }
