from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Verify claims" in response.text
    assert "Demo mode" in response.text
    assert "instead of opening index.html directly" in response.text


def test_health_endpoint():
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Saphes"
    assert payload["mode"] in {"live", "offline"}


def test_verify_endpoint_returns_renderable_results():
    response = client.post(
        "/api/verify",
        json={"answer": "Our platform uses API version 2.0 and costs $20/month."},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_mode"] in {"live", "cached", "mixed", "heuristic"}
    assert payload["claims_checked"] == len(payload["results"])
    assert sum(payload["summary"].values()) == payload["claims_checked"]
    assert all(
        result["verdict"] in {"current", "stale", "uncertain", "non_factual"}
        and isinstance(result["sources"], list)
        for result in payload["results"]
    )
    assert "access-control-allow-origin" not in response.headers


def test_verify_endpoint_rejects_blank_answer():
    response = client.post("/api/verify", json={"answer": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Answer text is required."


def test_verify_endpoint_rejects_non_string_answer():
    response = client.post("/api/verify", json={"answer": 123})

    assert response.status_code == 422
