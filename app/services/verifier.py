from __future__ import annotations

from app.models import ClaimVerdict
from app.services.claim_extractor import extract_claims
from app.services.evidence_service import evaluate_claim
from app.services.external_adapters import extract_claims_via_bifrost


def verify_answer(answer: str) -> dict:
    normalized_claims = extract_claims_via_bifrost(answer)
    claims = [
        type("ClaimProxy", (), {"text": item["text"], "volatility": item.get("volatility", "medium"), "category": item.get("category", "general"), "confidence": item.get("confidence", 0.7)})()
        for item in normalized_claims
    ] if normalized_claims else extract_claims(answer)

    verdicts: list[ClaimVerdict] = [evaluate_claim(claim) for claim in claims]

    counts = {"current": 0, "stale": 0, "uncertain": 0}
    for item in verdicts:
        counts[item.verdict] += 1

    return {
        "answer": answer,
        "claims_checked": len(claims),
        "summary": counts,
        "results": [item.to_dict() for item in verdicts],
    }
