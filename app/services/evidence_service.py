"""Verdict engine.

A verdict is produced in one of two ways:

1. **Evidence-based** (the real path). The claim becomes a search query, the live
   web is searched, the asserted values (version, price, percentage) are pulled
   out of both sides and compared. This is what makes Saphes a detector rather
   than a lookup table.
2. **Deterministic fallback** (offline / no network). A small set of rules keeps
   the application honest and testable without external calls. It is clearly
   labelled in the response so nothing is ever passed off as live evidence.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from app.models import Claim, ClaimVerdict, EvidenceSource
from app.services.external_adapters import EvidenceSearch, search_evidence
from app.services.signals import (
    _version_tuple as version_tuple,
    extract_claim_signals,
    extract_evidence_signals,
    highest_version,
    lexical_overlap,
    parse_amount,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_for_matching(text: str) -> str:
    return re.sub(r"[^a-z0-9\s$./-]", " ", text.lower()).strip()


# --------------------------------------------------------------------------- #
# evidence-based judging
# --------------------------------------------------------------------------- #

_NEEDLE_RE = re.compile(r"\d+(?:\.\d+)+")


def _snippet_for(content: str, needles: list[str]) -> tuple[str, str | None]:
    """Show the part of the page that carries the value, and say which token matched."""
    for needle in needles:
        index = content.find(needle)
        if index < 0:
            continue
        start = max(0, index - 90)
        end = min(len(content), index + 150)
        window = content[start:end].strip()
        snippet = f"…{window}…" if start or end < len(content) else window
        return snippet, needle
    return content[:230], None


def _sources_from(search: EvidenceSearch, needles: list[str] | None = None) -> list[EvidenceSource]:
    captured = search.captured_at if search.mode == "cached" else None
    needles = needles or []
    sources: list[EvidenceSource] = []
    for item in search.results:
        snippet, match = _snippet_for(item.get("content", ""), needles)
        sources.append(
            EvidenceSource(
                name=item["title"],
                url=item["url"],
                snippet=snippet,
                captured_at=captured,
                match=match,
            )
        )
    return sources


def _price_period(price: str) -> tuple[str, str]:
    amount, _, period = price.partition("/")
    return amount.strip(), period.strip()


def judge_with_evidence(claim: Claim, search: EvidenceSearch, query: str) -> ClaimVerdict:
    snippets = [item.get("content", "") for item in search.results]
    claim_signals = claim.signals or extract_claim_signals(claim.text)
    evidence_signals = extract_evidence_signals(snippets)

    needles: list[str] = []
    for value in evidence_signals.get("version", []) + evidence_signals.get("price", []):
        needles.extend(_NEEDLE_RE.findall(value))
    for value in claim_signals.get("version", []) + claim_signals.get("price", []):
        needles.extend(_NEEDLE_RE.findall(value))
    sources = _sources_from(search, needles)

    def verdict(
        kind: str,
        explanation: str,
        confidence: float,
        asserted: str | None = None,
        current: str | None = None,
    ) -> ClaimVerdict:
        return ClaimVerdict(
            claim=claim.text,
            verdict=kind,  # type: ignore[arg-type]
            explanation=explanation,
            confidence=confidence,
            volatility=claim.volatility,
            checked_at=_now(),
            sources=sources,
            asserted_value=asserted,
            current_value=current,
            query=query,
            evidence_mode=search.mode,  # type: ignore[arg-type]
            note=search.note,
        )

    # 1. prices - the highest-signal kind of drift
    claim_prices = claim_signals.get("price", [])
    evidence_prices = evidence_signals.get("price", [])
    if claim_prices and evidence_prices:
        asserted = claim_prices[0]
        asserted_amount, asserted_period = _price_period(asserted)
        asserted_number = parse_amount(asserted_amount)

        same_period = []
        for candidate in evidence_prices:
            amount, period = _price_period(candidate)
            if period == asserted_period:
                same_period.append((candidate, parse_amount(amount)))

        if same_period:
            for candidate, number in same_period:
                if number is not None and number == asserted_number:
                    return verdict(
                        "current",
                        f"The live source lists the same price ({candidate}), so this claim still holds.",
                        0.86,
                        asserted=candidate,
                        current=candidate,
                    )
            candidate = same_period[0][0]
            return verdict(
                "stale",
                f"This claim says {asserted}; the source we found now lists {candidate}. "
                "The number moved, so the sentence is out of date even though it was true once.",
                0.82,
                asserted=asserted,
                current=candidate,
            )

    # 2. versions - compared numerically, not by string presence. A release-notes
    #    page that *mentions* 0.100.0 does not make 0.100.0 current.
    claim_versions = claim_signals.get("version", [])
    evidence_versions = evidence_signals.get("version", [])
    if claim_versions and evidence_versions:
        asserted = claim_versions[0]
        current = highest_version(evidence_versions, same_major_as=asserted)
        try:
            asserted_number = version_tuple(asserted)
            current_number = version_tuple(current) if current else None
        except ValueError:
            asserted_number, current_number = None, None

        if asserted_number and current_number:
            if asserted_number == current_number:
                return verdict(
                    "current",
                    f"{asserted} is still the current documented release.",
                    0.78,
                    asserted=asserted,
                    current=asserted,
                )
            if current_number > asserted_number:
                return verdict(
                    "stale",
                    f"This claim asserts {asserted} as the current version. The sources fetched "
                    f"just now mention releases up to {current}, so {asserted} is no longer the "
                    "latest - the drift a model's training data cannot see.",
                    0.74,
                    asserted=asserted,
                    current=current,
                )
            return verdict(
                "uncertain",
                f"This claim asserts {asserted}, which is newer than anything the sources we found "
                f"mention (highest seen: {current}). Too new to confirm.",
                0.42,
                asserted=asserted,
                current=current,
            )

    # 3. percentages
    claim_percents = claim_signals.get("percent", [])
    evidence_percents = evidence_signals.get("percent", [])
    if claim_percents and evidence_percents and claim_percents[0] not in evidence_percents:
        return verdict(
            "stale",
            f"This claim asserts {claim_percents[0]}; the sources we found report "
            f"{', '.join(evidence_percents[:3])}.",
            0.62,
            asserted=claim_percents[0],
            current=evidence_percents[0],
        )

    # 4. no comparable value - be explicit about the limits of the check
    overlap = lexical_overlap(claim.text, snippets)
    if overlap >= 0.7:
        return verdict(
            "current",
            "The pages we found discuss this claim and assert no conflicting value, so we found "
            "no evidence of drift. This is the weakest of our three verdicts.",
            0.52,
        )
    if overlap >= 0.3:
        return verdict(
            "uncertain",
            "The evidence is related but does not state this claim specifically. We will not mark "
            "something current on a vague match.",
            0.45,
        )

    return verdict(
        "uncertain",
        "No page among the top results states this claim. It may be private, internal, or simply "
        "too new. We report that rather than guessing.",
        0.35,
    )


# --------------------------------------------------------------------------- #
# deterministic fallback (offline / no network / unit tests)
# --------------------------------------------------------------------------- #

def deterministic_verdict(claim: Claim) -> ClaimVerdict:
    normalized = _normalize_for_matching(claim.text)

    def verdict(kind: str, explanation: str, confidence: float) -> ClaimVerdict:
        return ClaimVerdict(
            claim=claim.text,
            verdict=kind,  # type: ignore[arg-type]
            explanation=explanation,
            confidence=confidence,
            volatility=claim.volatility,
            checked_at=_now(),
            sources=[],
            evidence_mode="heuristic",
        )

    if "version 2.0" in normalized or "v2.0" in normalized or "api version 2 0" in normalized:
        return verdict(
            "stale",
            "Offline fallback: the built-in rule treats API version 2.0 as superseded. "
            "No live source was consulted for this verdict.",
            0.92,
        )

    if "$20" in normalized and "month" in normalized:
        return verdict(
            "stale",
            "Offline fallback: the built-in rule treats $20/month as superseded by the "
            "current standard plan. No live source was consulted for this verdict.",
            0.88,
        )

    if "product x" in normalized:
        return verdict(
            "current",
            "Offline fallback: the built-in rule recognises this integration as supported. "
            "No live source was consulted for this verdict.",
            0.83,
        )

    if "regulation" in normalized or "compliance" in normalized or "gdpr" in normalized:
        return verdict(
            "uncertain",
            "Offline fallback: legal and regulatory claims need a human-grade source; "
            "we will not guess at them.",
            0.64,
        )

    return verdict(
        "uncertain",
        "Offline fallback: no rule matched and no live evidence was available. "
        "Reported as uncertain on purpose.",
        0.51,
    )


def evaluate_claim(claim: Claim, allow_live: bool = True, query: str | None = None) -> ClaimVerdict:
    """Try live evidence first, fall back to the deterministic rules."""
    from app.services.claim_extractor import build_search_query

    search_query = query or build_search_query(claim.text, claim.category)
    search_ms = 0

    if allow_live:
        started = time.perf_counter()
        search = search_evidence(search_query, allow_live=True)
        search_ms = max(1, int((time.perf_counter() - started) * 1000))
        if search.results:
            started = time.perf_counter()
            verdict = judge_with_evidence(claim, search, search_query)
            verdict.search_ms = search_ms
            verdict.compare_ms = max(0, int((time.perf_counter() - started) * 1000))
            return verdict

    verdict = deterministic_verdict(claim)
    verdict.search_ms = search_ms
    return verdict
