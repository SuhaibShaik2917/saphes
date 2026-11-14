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
            explanation="The local demo rule marks API version 2.0 as stale; no live documentation was checked.",
            confidence=0.92,
            volatility=claim.volatility,
            sources=_build_sources(
                "Example API documentation (demo)",
                "https://example.com/docs/api-versioning",
                "Placeholder source; the local demo data represents version 3.0 as current.",
            ),
        )

    if "$20/month" in normalized or "$20 / month" in normalized or "$20" in normalized and "month" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="stale",
            explanation="The local demo rule marks $20/month as stale; no live pricing page was checked.",
            confidence=0.88,
            volatility=claim.volatility,
            sources=_build_sources(
                "Example pricing page (demo)",
                "https://example.com/pricing",
                "Placeholder source; the local demo data represents the standard plan at $24/month.",
            ),
        )

    if "product x" in normalized or "supports integration with product x" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="current",
            explanation="The local demo rule recognizes Product X; no live integration documentation was checked.",
            confidence=0.83,
            volatility=claim.volatility,
            sources=_build_sources(
                "Example integration documentation (demo)",
                "https://example.com/integrations/product-x",
                "Placeholder source; the local demo data lists Product X as supported.",
            ),
        )

    if "regulation" in normalized or "compliance" in normalized:
        return ClaimVerdict(
            claim=claim.text,
            verdict="uncertain",
            explanation="Local demo rules cannot verify this time-sensitive claim; check current legal material directly.",
            confidence=0.64,
            volatility=claim.volatility,
            sources=_build_sources(
                "Example regulatory tracker (demo)",
                "https://example.com/legal/updates",
                "Placeholder source; no live legal source was queried.",
            ),
        )

    return ClaimVerdict(
        claim=claim.text,
        verdict="uncertain",
        explanation="Local demo rules did not match this claim; no live evidence was fetched.",
        confidence=0.51,
        volatility=claim.volatility,
        sources=[
            EvidenceSource(
                name="Example fallback search (demo)",
                url="https://example.com/search?q=" + claim.text.replace(" ", "+"),
                snippet="Placeholder source; no live web search was performed.",
            )
        ],
    )


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
