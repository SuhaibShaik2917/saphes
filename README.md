# Saphes

Saphes is a prototype verification layer for AI-generated answers. It extracts individual factual claims, evaluates their freshness against current evidence, and returns a per-claim verdict with a source-backed explanation.

This project follows the hackathon brief for a stale-answer detector, but keeps the implementation practical and extensible: the extraction logic, verification engine, and adapter seams are structured so they can later plug into real Bifrost and Tavily integrations.

The current build is a demo: it uses deterministic local heuristics and does not fetch live evidence. The `example.com` sources are placeholders, not citations. The Bifrost and Tavily adapters are extension points only; configuring keys does not enable live integrations yet.

## What the prototype does

- Extracts factual claims from a pasted answer.
- Classifies high-volatility claims such as API versions, pricing, product integration claims, and regulatory references.
- Uses local demo rules to illustrate stale, current, and uncertain verdicts.
- Returns a verdict for each claim in a developer-friendly JSON format.
- Serves a lightweight dashboard to test the flow in a browser.

## Tech stack

- Python
- FastAPI
- Pydantic
- Pytest
- HTML / JavaScript / CSS

## Local setup

1. Create a virtual environment with Python 3.13 (preferred for compatibility with the pinned dependency set in this project).
2. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Run the API:

   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

4. Open the browser at:

   ```text
   http://localhost:8000/
   ```

If port 8000 is blocked on your machine, run with a different port. In PowerShell:

```powershell
$env:TRUTHLAYER_PORT = "8010"
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

## Example API request

```bash
curl -X POST http://localhost:8000/api/verify \
  -H "Content-Type: application/json" \
  -d '{"answer":"Our platform uses API version 2.0, costs $20/month, and supports integration with Product X."}'
```

## Project structure

```text
Saphes/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── services/
│   │   ├── claim_extractor.py
│   │   ├── evidence_service.py
│   │   ├── external_adapters.py
│   │   └── verifier.py
│   └── static/
│       └── index.html
├── tests/
│   ├── test_api.py
│   └── test_verifier.py
├── .gitignore
├── .env.example
├── requirements.txt
└── README.md
```

## Notes on the roadmap

This is intentionally designed as a working prototype rather than a fixed specification. The current logic uses local, deterministic demo rules so the system is testable without external API keys, while the project structure is prepared for Bifrost/Tavily integration when those services are implemented.

The adapter layer lives in [app/services/external_adapters.py](app/services/external_adapters.py) and is designed to be swapped for real service calls when the project is wired to production credentials.
