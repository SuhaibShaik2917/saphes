from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import APP_NAME, OFFLINE_MODE, SAPHES_HOST, SAPHES_PORT
from app.services.verifier import verify_answer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_NAME, version="0.2.0")


class VerificationRequest(BaseModel):
    answer: str
    allow_live: bool | None = None


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": APP_NAME,
        "mode": "offline" if OFFLINE_MODE else "live",
    }


@app.post("/api/verify")
def verify_endpoint(payload: VerificationRequest) -> dict:
    if not payload.answer or not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Answer text is required.")
    return verify_answer(payload.answer, allow_live=payload.allow_live)


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=SAPHES_HOST, port=SAPHES_PORT, reload=True)
