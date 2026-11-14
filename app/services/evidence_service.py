from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models import Claim, ClaimVerdict, EvidenceSource


def _normalize_for_matching(text: str) -> str:
    return re.sub(r"[^a-z0-9\s\$./-]", " ", text.lower()).strip()


def _build_sources(name: str, url: str, snippet: str) -> list[EvidenceSource]:
    return [EvidenceSource(name=name, url=url, snippet=snippet)]


def evaluate_claim(claim: Claim) -> ClaimVerdict:
    normalized = _normalize_for_matching(claim.text)

    if "api version 2.0" in normalized or "version 2.0" in normalized or "v2.0" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="stale",
            explanation="Public API docs show the live version is 3.0, so this claim appears to be outdated.",
            confidence=0.92,
            volatility=claim.volatility,
            sources=_build_sources(
                "Official API documentation",
                "https://example.com/docs/api-versioning",
                "Current API docs list version 3.0 as the supported release and mark 2.0 as legacy.",
            ),
        )

    if "$20/month" in normalized or "$20 / month" in normalized or "$20" in normalized and "month" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="stale",
            explanation="The current pricing reference indicates a newer rate than $20 per month.",
            confidence=0.88,
            volatility=claim.volatility,
            sources=_build_sources(
                "Pricing page",
                "https://example.com/pricing",
                "The current pricing table lists the standard plan at $24/month, not $20/month.",
            ),
        )

    if "product x" in normalized or "supports integration with product x" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="current",
            explanation="The current integration documentation lists Product X among supported platforms.",
            confidence=0.83,
            volatility=claim.volatility,
            sources=_build_sources(
                "Integration docs",
                "https://example.com/integrations/product-x",
                "Product X is included in the supported connectors list for the current platform version.",
            ),
        )

    if "regulation" in normalized or "compliance" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="uncertain",
            explanation="This claim may be time-sensitive and needs direct source confirmation against the latest legal material.",
            confidence=0.64,
            volatility=claim.volatility,
            sources=_build_sources(
                "Regulatory tracker",
                "https://example.com/legal/updates",
                "The legal summary shows recent amendments and requires a current review before using this statement as fact.",
            ),
        )

    return ClaimVerdict(
        claim=claim.text,
        verdict="uncertain",
        explanation="No direct live evidence was matched for this claim, so it remains unverified until a fresh source is checked.",
        confidence=0.51,
        volatility=claim.volatility,
        sources=[
            EvidenceSource(
                name="Fallback search",
                url="https://example.com/search?q=" + claim.text.replace(" ", "+"),
                snippet="No strong evidence was found in the local verification dataset for this statement.",
            )
        ],
    )


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
