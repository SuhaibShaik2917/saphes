"""Value-level comparison between a claim and the evidence found for it.

The point of this module is that Saphes does not decide a verdict by looking for
the literal string "API version 2.0". It pulls the *asserted values* out of the
claim (a version, a price, a percentage, a year), pulls the values out of the
evidence, and compares them. That is the difference between a demo rule and a
detector.
"""

from __future__ import annotations

import re
from typing import Iterable

PRICE_RE = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:/|per\s+)\s*"
    r"(month|year|day|week|quarter|user|seat|\d[\d,]*\s*tokens?)",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

VERSION_HINT_RE = re.compile(r"\b(version|api|sdk|release|v\d|upgrade|deprecat)",
                             re.IGNORECASE)

STOPWORDS = {
    "the", "our", "and", "for", "with", "that", "this", "from", "your", "have",
    "has", "are", "was", "were", "will", "can", "you", "its", "it's", "their",
    "they", "them", "there", "here", "into", "over", "under", "about", "using",
    "uses", "use", "used", "also", "more", "most", "than", "then", "when",
    "which", "while", "what", "who", "how", "all", "any", "each", "some",
    "platform", "product", "answer", "claim", "currently", "current", "now",
    "latest", "new", "old", "still", "per", "month", "year", "day",
}


def _norm_price(amount: str, period: str) -> str:
    period = period.lower().strip()
    period = re.sub(r"\s+", " ", period)
    return f"${amount}/{period}"


def extract_claim_signals(text: str) -> dict[str, list[str]]:
    """Values asserted by the claim itself."""
    signals: dict[str, list[str]] = {}

    prices = [_norm_price(m.group(1), m.group(2)) for m in PRICE_RE.finditer(text)]
    if prices:
        signals["price"] = prices

    versions = []
    if VERSION_HINT_RE.search(text):
        versions = [f"v{m.group(1)}" for m in VERSION_RE.finditer(text)]
    if versions:
        signals["version"] = versions

    percents = [f"{m.group(1)}%" for m in PERCENT_RE.finditer(text)]
    if percents:
        signals["percent"] = percents

    years = [m.group(0) for m in YEAR_RE.finditer(text)]
    if years:
        signals["year"] = sorted(set(years))

    return signals


def extract_evidence_signals(snippets: Iterable[str]) -> dict[str, list[str]]:
    """Values asserted by the evidence pages, in document order."""
    prices: list[str] = []
    versions: list[str] = []
    percents: list[str] = []

    for snippet in snippets:
        for match in PRICE_RE.finditer(snippet):
            price = _norm_price(match.group(1), match.group(2))
            if price not in prices:
                prices.append(price)
        for match in VERSION_RE.finditer(snippet):
            version = f"v{match.group(1)}"
            if version not in versions:
                versions.append(version)
        for match in PERCENT_RE.finditer(snippet):
            percent = f"{match.group(1)}%"
            if percent not in percents:
                percents.append(percent)

    signals: dict[str, list[str]] = {}
    if prices:
        signals["price"] = prices
    if versions:
        signals["version"] = versions
    if percents:
        signals["percent"] = percents
    return signals


def parse_amount(value: str) -> float | None:
    """`"$1,024.50/month"` -> 1024.5, for numeric comparison."""
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.lstrip("v").split("."))


def highest_version(versions: list[str], same_major_as: str | None = None) -> str | None:
    """Highest version in the evidence.

    ``same_major_as`` keeps unrelated release trains out of the comparison: a page
    that mentions "1.0" somewhere must not outrank a 0.x product line.
    """
    candidates = [v for v in versions if re.fullmatch(r"v\d+(\.\d+)*", v)]
    if same_major_as:
        try:
            major = _version_tuple(same_major_as)[0]
            narrowed = [v for v in candidates if _version_tuple(v)[0] == major]
            candidates = narrowed or candidates
        except ValueError:  # pragma: no cover - defensive
            pass
    if not candidates:
        return None
    try:
        return max(candidates, key=_version_tuple)
    except ValueError:  # pragma: no cover - defensive
        return candidates[0]


def lexical_overlap(claim: str, snippets: Iterable[str]) -> float:
    """Fraction of the claim's content words that appear in the evidence."""
    words = {
        word
        for word in re.findall(r"[a-z][a-z0-9\-]{3,}", claim.lower())
        if word not in STOPWORDS
    }
    if not words:
        return 0.0

    haystack = " ".join(snippets).lower()
    hits = sum(1 for word in words if word in haystack)
    return hits / len(words)
