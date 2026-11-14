from __future__ import annotations

from typing import Any

from app.config import BIFROST_API_KEY, TAVILY_API_KEY


def has_external_credentials() -> bool:
    return bool(BIFROST_API_KEY and BIFROST_API_KEY != "demo-key" and TAVILY_API_KEY and TAVILY_API_KEY != "demo-key")


def extract_claims_via_bifrost(answer: str) -> list[dict[str, Any]] | None:
    """Hook for a real Bifrost-backed claim extraction layer.

    The prototype intentionally falls back to local extraction unless the caller has
    configured real Bifrost + Tavily credentials. This keeps the app testable while
    preserving the integration seam required by the hackathon brief.
    """
    if not has_external_credentials():
        return None

    # Real implementation would call the configured Bifrost endpoint here.
    return []


def search_evidence_via_tavily(query: str) -> list[dict[str, Any]] | None:
    """Hook for a real Tavily-backed evidence lookup."""
    if not has_external_credentials():
        return None

    # Real implementation would call the Tavily search API here.
    return []
