from app.services.repair import repair_answer
from app.services.verifier import risk_score, verify_answer


def test_repair_rewrites_a_stale_version_in_place():
    answer = "FastAPI is on version 0.100.0 and that is current."
    result = repair_answer(answer, [{"asserted": "v0.100.0", "current": "v0.146.0"}])

    assert result["changed"] is True
    assert "0.146.0" in result["corrected_answer"]
    assert "0.100.0" not in result["corrected_answer"]
    assert result["edits"] == [{"asserted": "v0.100.0", "current": "v0.146.0"}]


def test_repair_matches_price_spellings_used_in_prose():
    for sentence in (
        "The plan costs $20/month.",
        "The plan costs $20 / month.",
        "The plan costs $20 per month.",
    ):
        result = repair_answer(sentence, [{"asserted": "$20/month", "current": "$30/month"}])
        assert "$30/month" in result["corrected_answer"], sentence


def test_repair_does_not_inject_a_style_the_answer_never_used():
    result = repair_answer("Python 3.9 is the latest release.", [{"asserted": "v3.9", "current": "v3.14"}])

    assert "3.14" in result["corrected_answer"]
    assert "v3.14" not in result["corrected_answer"]


def test_repair_is_a_no_op_without_corrections():
    result = repair_answer("Nothing stale here.", [])

    assert result["corrected_answer"] == "Nothing stale here."
    assert result["changed"] is False


def test_verification_exposes_trace_and_repair():
    result = verify_answer("Our platform uses API version 2.0 and costs $20/month.")

    steps = [item["step"] for item in result["trace"]]
    assert steps[0] == "split the answer into claims"
    assert "searched the live web" in steps
    assert "repaired the answer" in steps
    assert all(isinstance(item["ms"], int) for item in result["trace"])
    assert set(result["repair"]) == {"corrected_answer", "edits", "changed"}


def test_results_are_ordered_by_risk_so_the_worst_is_first():
    result = verify_answer("Our platform uses API version 2.0 and costs $20/month.")

    risks = [item["risk_score"] for item in result["results"]]
    priorities = [item["priority"] for item in result["results"]]
    assert risks == sorted(risks, reverse=True)
    assert priorities == list(range(1, len(priorities) + 1))
    assert result["results"][0]["risk_label"] in {"act now", "cannot confirm", "holds"}


def test_risk_score_ranks_a_stale_high_volatility_claim_above_a_current_one():
    result = verify_answer("Our platform uses API version 2.0 and costs $20/month.")

    by_verdict = {item["verdict"]: item for item in result["results"]}
    if "stale" in by_verdict and "current" in by_verdict:
        assert by_verdict["stale"]["risk_score"] > by_verdict["current"]["risk_score"]
