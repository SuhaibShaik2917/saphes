from __future__ import annotations

import re

from app.models import Claim
from app.services.signals import extract_claim_signals

_SPLIT_RE = re.compile(
    r",(?!\d{3})|;|\s+and\s+|\s+but\s+|\s+however\s+|\s+whereas\s+", re.IGNORECASE
)
_SUBJECT_START_RE = re.compile(
    r"^(our|we|the|its|it|they|this|that|these|those|all|my|his|her|their|there|"
    r"you|your|i|a|an|each|every|most|some|no|not)\b",
    re.IGNORECASE,
)
_VERB_START_RE = re.compile(
    r"^(costs?|supports?|includes?|offers?|requires?|runs?|is|are|was|were|uses?|"
    r"has|have|provides?|depends?|allows?|integrates?|works?|ships?|removes?|"
    r"released?|supports?)\b",
    re.IGNORECASE,
)

# Frames that carry no searchable information ("Our platform uses ...").
_FRAME_RE = re.compile(
    r"\b(our|my|the platform|this platform|their|we|us|i|the product|this product)\b",
    re.IGNORECASE,
)

_CATEGORY_QUERY_HINT = {
    "api_version": "latest version release notes",
    "pricing": "pricing current price",
    "regulation": "current regulation status",
    "integration": "documentation supported integration",
    "company_info": "latest announcement",
    "general": "latest",
}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _classify_claim(segment: str) -> tuple[str, str]:
    normalized = segment.lower()

    if re.search(r"\b(api|sdk|endpoint|version|v\d+)(?:\s+|\D+)(?:version\s+)?v?\d+(?:\.\d+)*", normalized):
        return "api_version", "high"
    if re.search(r"\$\s?\d+(?:\.\d+)?\s*(?:/|per\s+)(month|year|day|week|quarter|user|seat)", normalized):
        return "pricing", "high"
    if re.search(r"\b(gdpr|ccpa|hipaa|sox|regulation|compliance|policy|law)\b", normalized):
        return "regulation", "high"
    if re.search(r"\b(supports|integrates|works with|compatible with|partner(?:s|ed)? with|connects to)\b", normalized):
        return "integration", "medium"
    if re.search(r"\b(company|product|launch|release|pricing|roadmap|partnership|customer)\b", normalized):
        return "company_info", "medium"
    return "general", "medium"


_VERB_WORDS = {
    "uses", "use", "using", "costs", "cost", "is", "are", "was", "were", "supports",
    "support", "includes", "include", "offers", "provide", "provides", "requires",
    "runs", "has", "have", "ships", "released", "allows", "integrates", "works",
    "depends", "gives", "lets", "makes",
}


def _subject_of(sentence: str) -> str:
    """The leading noun phrase a trailing fragment lost when it was split.

    "The Tavily Project plan costs $20/month and includes X" -> "The Tavily Project plan"
    """
    words = sentence.split()
    subject: list[str] = []
    for word in words[:5]:
        bare = re.sub(r"[^\w$]", "", word).lower()
        if bare in _VERB_WORDS:
            break
        subject.append(word)
        if len(subject) == 4:
            break
    if subject:
        return " ".join(subject).rstrip(",:;")
    return " ".join(words[:2]) if len(words) >= 2 else sentence


def _restore_subject(sentence: str, part: str, index: int) -> str:
    """Keep split fragments readable: 'costs $20/month' -> 'Our platform costs $20/month'."""
    if index == 0:
        return part
    if _SUBJECT_START_RE.match(part) or not _VERB_START_RE.match(part):
        return part
    subject = _subject_of(sentence)
    if subject.lower() in part.lower():
        return part
    return f"{subject} {part}"


def build_search_query(claim_text: str, category: str = "general") -> str:
    """Turn a claim into a query a search engine can actually answer."""
    cleaned = _FRAME_RE.sub(" ", claim_text)
    cleaned = re.sub(r"[^\w\s.\-$/,]", " ", cleaned)
    cleaned = re.sub(r",(?!\d{3})", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    words = [word for word in cleaned.split() if len(word) > 1]
    query = " ".join(words[:10]).strip()

    hint = _CATEGORY_QUERY_HINT.get(category, "")
    if hint and hint.split()[0] not in query.lower():
        query = f"{query} {hint}".strip()

    return _normalize_space(query) or claim_text.strip()


def extract_claims(answer: str) -> list[Claim]:
    if not answer or not answer.strip():
        return []

    sentence_chunks = re.split(r"(?<=[.!?])\s+|\n+", answer)
    claims: list[Claim] = []

    for sentence in sentence_chunks:
        cleaned = _normalize_space(sentence)
        if not cleaned:
            continue

        parts = _SPLIT_RE.split(cleaned)
        for index, part in enumerate(parts):
            trimmed = _normalize_space(part)
            if not trimmed:
                continue

            trimmed = _normalize_space(_restore_subject(cleaned, trimmed, index))
            if len(trimmed) < 5:
                continue
            # A fragment must read as a claim: it needs letters and cannot open
            # with a stray digit left over from splitting "100,000 searches".
            if not re.match(r"[A-Za-z\"'(]", trimmed) or len(re.findall(r"[A-Za-z]", trimmed)) < 3:
                continue

            category, volatility = _classify_claim(trimmed)
            confidence = 0.86 if volatility == "high" else 0.72
            claims.append(
                Claim(
                    text=trimmed,
                    volatility=volatility,
                    category=category,
                    confidence=confidence,
                    signals=extract_claim_signals(trimmed),
                )
            )

    if not claims:
        text = _normalize_space(answer)
        claims.append(
            Claim(
                text=text,
                volatility="medium",
                category="general",
                confidence=0.6,
                signals=extract_claim_signals(text),
            )
        )

    return claims
