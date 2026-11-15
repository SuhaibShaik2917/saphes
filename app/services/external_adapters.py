"""Adapters to the outside world.

Saphes has exactly two seams:

* ``extract_claims_via_bifrost`` - claim extraction through an LLM gateway.
  Still a stub; the deterministic extractor is the shipped path.
* ``search_evidence`` - live web evidence. This one is REAL and needs no API
  key: Tavily's keyless access mode returns live results without a signup.

Every network call is time-boxed and every failure is absorbed. A verification
request must never raise because the internet was slow - it degrades to cached
evidence, then to the deterministic rules.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import (
    BIFROST_API_KEY,
    BUNDLED_EVIDENCE,
    CACHE_DIR,
    OFFLINE_MODE,
    TAVILY_API_KEY,
    TAVILY_MAX_RESULTS,
    TAVILY_SEARCH_URL,
    TAVILY_TIMEOUT_SECONDS,
)


class RateLimited(RuntimeError):
    """The keyless search allowance is exhausted. Fall back, never fail."""


@dataclass
class EvidenceSearch:
    results: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "heuristic"
    captured_at: str | None = None
    note: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def has_external_credentials() -> bool:
    """Kept for the Bifrost seam: both keys must be real to enable it."""
    return bool(
        BIFROST_API_KEY
        and BIFROST_API_KEY != "demo-key"
        and TAVILY_API_KEY
        and TAVILY_API_KEY != "demo-key"
    )


def extract_claims_via_bifrost(answer: str) -> list[dict[str, Any]] | None:
    """Hook for an LLM-backed claim extraction layer.

    Returns ``None`` so the caller uses the deterministic extractor. Wiring a
    real gateway here is a single function body - that is the point of the seam.
    """
    if not has_external_credentials():
        return None
    return None


# --------------------------------------------------------------------------- #
# caching
# --------------------------------------------------------------------------- #

def _cache_key(query: str) -> str:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _cache_path(query: str) -> str:
    return os.path.join(CACHE_DIR, "search", f"{_cache_key(query)}.json")


def _read_cache(query: str) -> dict[str, Any] | None:
    path = _cache_path(query)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _write_cache(query: str, results: list[dict[str, Any]]) -> None:
    path = _cache_path(query)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"query": query, "captured_at": _now(), "results": results}, handle)
    except OSError:  # pragma: no cover - cache is best-effort
        pass


def _read_bundled_evidence(query: str) -> dict[str, Any] | None:
    """A recorded run captured during the build, used when the network dies."""
    if not os.path.exists(BUNDLED_EVIDENCE):
        return None
    try:
        with open(BUNDLED_EVIDENCE, "r", encoding="utf-8") as handle:
            bundled = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return bundled.get(_cache_key(query))


# --------------------------------------------------------------------------- #
# live search
# --------------------------------------------------------------------------- #

def _clean_content(text: str, limit: int = 300) -> str:
    """Strip markdown noise from scraped page text so a card reads clean."""
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF]+", "", text or "")
    cleaned = re.sub(r"[#|*`>\[\]]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rsplit(" ", 1)[0] + "…"
    return cleaned


def _clean_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": _clean_content(item.get("title", ""), 140),
            "url": item.get("url", ""),
            "content": _clean_content(item.get("content", "")),
        }
        for item in results
        if item.get("url")
    ]


def _http_search(query: str) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TAVILY_API_KEY:
        headers["Authorization"] = f"Bearer {TAVILY_API_KEY}"
    else:
        # Tavily's free, rate-limited keyless mode - no signup, no card.
        headers["X-Tavily-Access-Mode"] = "keyless"

    with httpx.Client(timeout=TAVILY_TIMEOUT_SECONDS) as client:
        response = client.post(
            TAVILY_SEARCH_URL,
            headers=headers,
            json={"query": query, "max_results": TAVILY_MAX_RESULTS, "search_depth": "basic"},
        )
        if response.status_code == 429:
            try:
                message = response.json().get("error", {}).get("message", "")
            except Exception:  # pragma: no cover - non-JSON error body
                message = ""
            raise RateLimited(message or "keyless search allowance exhausted")
        response.raise_for_status()
        payload = response.json()

    results: list[dict[str, Any]] = []
    for item in payload.get("results", [])[:TAVILY_MAX_RESULTS]:
        url = item.get("url")
        if not url:
            continue
        results.append(
            {
                "title": item.get("title") or url,
                "url": url,
                "content": item.get("content") or "",
            }
        )
    return _clean_results(results)


def search_evidence(query: str, allow_live: bool = True) -> EvidenceSearch:
    """Search the live web for a claim. Never raises.

    Order: live -> disk cache -> bundled recording -> nothing.
    """
    query = query.strip()
    if not query:
        return EvidenceSearch()

    note: str | None = None

    if allow_live and not OFFLINE_MODE:
        try:
            results = _http_search(query)
            if results:
                _write_cache(query, results)
                return EvidenceSearch(results=results, mode="live", captured_at=_now())
            note = "live search returned no results"
        except RateLimited:
            note = "hourly live-search limit reached"
        except httpx.TimeoutException:
            note = "live search timed out"
        except Exception:  # DNS, TLS, 5xx
            note = "live search unavailable"

    cached = _read_cache(query)
    if cached and cached.get("results"):
        return EvidenceSearch(
            results=_clean_results(cached["results"]),
            mode="cached",
            captured_at=cached.get("captured_at"),
            note=note,
        )

    bundled = _read_bundled_evidence(query)
    if bundled and bundled.get("results"):
        return EvidenceSearch(
            results=_clean_results(bundled["results"]),
            mode="cached",
            captured_at=bundled.get("captured_at"),
            note=note or "recorded evidence bundle",
        )

    return EvidenceSearch(note=note)
