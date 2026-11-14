from app.services.verifier import verify_answer


def test_extracts_claims_from_mixed_answer():
    answer = "Our platform uses API version 2.0, costs $20/month, and supports integration with Product X."
    result = verify_answer(answer)

    assert result["claims_checked"] >= 3
    assert any(item["claim"] for item in result["results"])


def test_detects_stale_api_version_and_pricing():
    answer = "Our platform uses API version 2.0 and costs $20/month."
    result = verify_answer(answer)

    verdicts = {item["claim"]: item["verdict"] for item in result["results"]}
    stale_matches = [
        verdicts.get(item["claim"], "uncertain")
        for item in result["results"]
        if "API version 2.0" in item["claim"] or "$20/month" in item["claim"]
    ]

    assert any(verdict == "stale" for verdict in stale_matches)


def test_reports_supported_integration_as_current():
    answer = "Our platform supports integration with Product X."
    result = verify_answer(answer)

    integration_result = next(
        (item for item in result["results"] if "Product X" in item["claim"]),
        None,
    )

    assert integration_result is not None
    assert integration_result["verdict"] == "current"
