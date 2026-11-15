from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

Volatility = Literal["low", "medium", "high"]
Verdict = Literal["current", "stale", "uncertain"]
EvidenceMode = Literal["live", "mixed", "cached", "heuristic"]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "") or url
    except Exception:  # pragma: no cover - defensive
        return url


@dataclass
class EvidenceSource:
    name: str
    url: str
    snippet: str
    captured_at: str | None = None
    match: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "domain": _domain(self.url),
            "snippet": self.snippet,
            "captured_at": self.captured_at,
            "match": self.match,
        }


@dataclass
class Claim:
    text: str
    volatility: Volatility
    category: str
    confidence: float = 0.0
    signals: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "volatility": self.volatility,
            "category": self.category,
            "confidence": self.confidence,
            "signals": self.signals,
        }


@dataclass
class ClaimVerdict:
    claim: str
    verdict: Verdict
    explanation: str
    confidence: float
    volatility: Volatility
    checked_at: str
    sources: list[EvidenceSource] = field(default_factory=list)
    asserted_value: str | None = None
    current_value: str | None = None
    query: str | None = None
    evidence_mode: EvidenceMode = "heuristic"
    note: str | None = None
    search_ms: int = 0
    compare_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "volatility": self.volatility,
            "checked_at": self.checked_at,
            "sources": [source.to_dict() for source in self.sources],
            "asserted_value": self.asserted_value,
            "current_value": self.current_value,
            "query": self.query,
            "evidence_mode": self.evidence_mode,
            "note": self.note,
        }
