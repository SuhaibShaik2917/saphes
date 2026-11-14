from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Volatility = Literal["low", "medium", "high"]
Verdict = Literal["current", "stale", "uncertain"]


@dataclass
class EvidenceSource:
    name: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "url": self.url,
            "snippet": self.snippet,
        }


@dataclass
class Claim:
    text: str
    volatility: Volatility
    category: str
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "volatility": self.volatility,
            "category": self.category,
            "confidence": self.confidence,
        }


@dataclass
class ClaimVerdict:
    claim: str
    verdict: Verdict
    explanation: str
    confidence: float
    volatility: Volatility
    sources: list[EvidenceSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "volatility": self.volatility,
            "sources": [source.to_dict() for source in self.sources],
        }
