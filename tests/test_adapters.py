from __future__ import annotations

import app.services.external_adapters as adapters
from app.models import Claim
from app.services.claim_extractor import build_search_query, extract_claims
from app.services.evidence_service import judge_with_evidence
from app.services.external_adapters import EvidenceSearch
from app.services.verifier import risk_band, staleness_index, verify_answer


def _claim(text: str, volatility: str = "high", category: str = "api_version") -> Claim:
    return Claim(text=text, volatility=volatility, category=category, confidence=0.86)


def _search(*contents: str, mode: str = "live") -> EvidenceSearch:
    return EvidenceSearch(
        mode=mode,
        captured_at="2026-11-14T18:00:00+00:00" if mode == "cached" else None,
        results=[
            {"title": f"Source {i}", "url": f"https://example.org/{i}", "content": text}
            for i, text in enumerate(contents, start=1)
        ],
    )


def test_search_uses_live_results_when_the_network_answers(monkeypatch):
    monkeypatch.setattr(adapters, "OFFLINE_MODE", False)
    monkeypatch.setattr(
        adapters,
        "_http_search",
        lambda query: [{"title": "Docs", "url": "https://docs.example.dev/v", "content": "current release 3.1"}],
    )

    result = adapters.search_evidence("api version latest")

    assert result.mode == "live"
    assert result.results[0]["url"] == "https://docs.example.dev/v"


def test_search_falls_back_to_cache_when_the_network_fails(monkeypatch):
    monkeypatch.setattr(adapters, "OFFLINE_MODE", False)
    monkeypatch.setattr(adapters, "CACHE_DIR", "/tmp/saphes-test-cache")

    cached_payload = {
        "query": "api version latest",
        "captured_at": "2026-11-14T18:00:00+00:00",
        "results": [{"title": "Cached", "url": "https://cache.example/doc", "content": "v3.0"}],
    }
    monkeypatch.setattr(adapters, "_read_cache", lambda query: cached_payload)

    def boom(query):
        raise TimeoutError("network down")

    monkeypatch.setattr(adapters, "_http_search", boom)

    result = adapters.search_evidence("api version latest")

    assert result.mode == "cached"
    assert result.results[0]["url"] == "https://cache.example/doc"


def test_rate_limited_search_falls_back_to_cache_with_a_visible_note(monkeypatch):
    monkeypatch.setattr(adapters, "OFFLINE_MODE", False)
    monkeypatch.setattr(adapters, "_read_cache", lambda query: {
        "query": "q",
        "captured_at": "2026-11-14T18:00:00+00:00",
        "results": [{"title": "Cached", "url": "https://cache.example/doc", "content": "v3.0"}],
    })

    def limited(query):
        raise adapters.RateLimited("hourly_cap_reached")

    monkeypatch.setattr(adapters, "_http_search", limited)

    result = adapters.search_evidence("some claim")

    assert result.mode == "cached"
    assert result.note == "hourly live-search limit reached"


def test_search_returns_empty_instead_of_raising(monkeypatch):
    monkeypatch.setattr(adapters, "OFFLINE_MODE", False)
    monkeypatch.setattr(adapters, "_read_cache", lambda query: None)
    monkeypatch.setattr(adapters, "_read_bundled_evidence", lambda query: None)

    def boom(query):
        raise RuntimeError("no internet")

    monkeypatch.setattr(adapters, "_http_search", boom)

    result = adapters.search_evidence("anything at all")

    assert result.results == []
    assert result.mode == "heuristic"


def test_price_drift_produces_a_stale_verdict_with_the_new_value():
    claim = _claim("Our platform costs $20/month", category="pricing")
    verdict = judge_with_evidence(claim, _search("Standard plan: $24/month billed annually."), "platform pricing")

    assert verdict.verdict == "stale"
    assert verdict.asserted_value == "$20/month"
    assert verdict.current_value == "$24/month"
    assert verdict.evidence_mode == "live"
    assert verdict.checked_at.endswith("+00:00")


def test_matching_price_is_current():
    claim = _claim("Our platform costs $24/month", category="pricing")
    verdict = judge_with_evidence(claim, _search("Standard plan: $24/month billed annually."), "platform pricing")

    assert verdict.verdict == "current"


def test_version_drift_produces_a_stale_verdict():
    claim = _claim("The SDK is on version 0.100.0")
    verdict = judge_with_evidence(
        claim,
        _search("Release notes: 0.115.0 is the current release. Older: 0.112.0."),
        "sdk version release notes",
    )

    assert verdict.verdict == "stale"
    assert verdict.current_value == "v0.115.0"


def test_unrelated_release_train_cannot_become_the_current_version():
    claim = _claim("The SDK is on version 0.100.0")
    verdict = judge_with_evidence(
        claim,
        _search("Release notes: 0.162.5 is the latest. Another library shipped 1.0 recently."),
        "sdk version",
    )

    assert verdict.verdict == "stale"
    assert verdict.current_value == "v0.162.5"


def test_version_present_in_documentation_is_current():
    claim = _claim("The SDK is on version 0.115.0")
    verdict = judge_with_evidence(claim, _search("Release notes: 0.115.0 shipped today."), "sdk version release notes")

    assert verdict.verdict == "current"


def test_unrelated_evidence_is_uncertain_not_current():
    claim = _claim("Our internal widget supports Product X", category="integration")
    verdict = judge_with_evidence(claim, _search("Weather forecast for Hyderabad."), "internal widget")

    assert verdict.verdict == "uncertain"
    assert verdict.confidence < 0.5


def test_cached_sources_are_labelled_with_capture_time():
    claim = _claim("Our platform costs $20/month", category="pricing")
    verdict = judge_with_evidence(
        claim, _search("Standard plan: $24/month.", mode="cached"), "platform pricing"
    )

    assert verdict.sources[0].captured_at == "2026-11-14T18:00:00+00:00"


def test_staleness_index_is_bounded_and_risk_banded():
    low = staleness_index([_claim("a") and judge_with_evidence(
        _claim("costs $24/month", category="pricing"), _search("$24/month"), "q")])
    high = staleness_index([judge_with_evidence(
        _claim("costs $20/month", category="pricing"), _search("$24/month"), "q")])

    assert 0.0 <= low <= 1.0
    assert low < high
    assert risk_band(0.1) == "low"
    assert risk_band(0.4) == "moderate"
    assert risk_band(0.9) == "high"


def test_claim_split_keeps_the_subject():
    claims = extract_claims("Our platform uses API version 2.0, costs $20/month, and supports Product X.")

    texts = [claim.text for claim in claims]
    assert any("$20/month" in text and "Our platform" in text for text in texts)
    assert len(claims) >= 3


def test_bulleted_lines_are_kept_as_claims():
    claims = extract_claims("- Python 3.9 is the latest release\n* The plan costs $20/month\n1. FastAPI is at 0.100.0")

    assert len(claims) >= 3


def test_very_long_answers_are_capped_and_say_so():
    answer = ". ".join(f"Service {i} costs ${i}/month" for i in range(1, 21)) + "."
    result = verify_answer(answer)

    assert result["claims_checked"] <= result["max_claims"]
    assert result["claims_truncated"] is True


def test_search_query_strips_first_person_framing():
    query = build_search_query("Our platform uses API version 2.0", "api_version")

    assert "our" not in query.lower().split()
    assert "2.0" in query


def test_verification_never_raises_and_reports_its_mode():
    result = verify_answer("Our platform uses API version 2.0 and costs $20/month.")

    assert result["evidence_mode"] in {"live", "cached", "mixed", "heuristic"}
    assert result["claims_checked"] == len(result["results"])
    assert 0.0 <= result["staleness_index"] <= 1.0
    assert result["risk_band"] in {"low", "moderate", "high"}
    assert result["checked_at"]
