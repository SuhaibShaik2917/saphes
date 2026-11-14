from __future__ import annotations

import re

from app.models import Claim


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _classify_claim(segment: str) -> tuple[str, str]:
    normalized = segment.lower()

    if re.search(r"\b(api|sdk|endpoint|version|v\d+)(?:\s+|\D+)(?:version\s+)?v?\d+(?:\.\d+)*", normalized):
        return "api_version", "high"
    if re.search(r"\$\d+(?:\.\d+)?\s*(?:/|per)\s*(month|year|day|quarter)", normalized):
        return "pricing", "high"
    if re.search(r"\b(gdpr|ccpa|hipaa|sox|regulation|compliance|policy|law)\b", normalized):
        return "regulation", "high"
    if re.search(r"\b(supports|integrates|works with|compatible with|partner(?:s|ed)? with|connects to)\b", normalized):
        return "integration", "medium"
    if re.search(r"\b(company|product|launch|release|pricing|roadmap|partnership|customer)\b", normalized):
        return "company_info", "medium"
    return "general", "medium"


def extract_claims(answer: str) -> list[Claim]:
    if not answer or not answer.strip():
        return []

    sentence_chunks = re.split(r"(?<=[.!?])\s+|\n+", answer)
    claims: list[Claim] = []

    for sentence in sentence_chunks:
        cleaned = _normalize_space(sentence)
        if not cleaned:
            continue

        split_parts = re.split(r"[,;]|\s+and\s+|\s+but\s+|\s+however\s+", cleaned)
        for part in split_parts:
            trimmed = _normalize_space(part)
            if not trimmed:
                continue

            if len(trimmed) < 5:
                continue

            category, volatility = _classify_claim(trimmed)
            claims.append(
                Claim(
                    text=trimmed,
                    volatility=volatility,
                    category=category,
                    confidence=0.78,
                )
            )

    if not claims:
        claims.append(
            Claim(
                text=_normalize_space(answer),
                volatility="medium",
                category="general",
                confidence=0.6,
            )
        )

    return claims
