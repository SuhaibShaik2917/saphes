from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import APP_NAME
from app.services.verifier import verify_answer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_NAME, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class VerificationRequest(BaseModel):
    answer: str


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok", "service": APP_NAME}


@app.post("/api/verify")
def verify_endpoint(payload: VerificationRequest) -> dict:
    if not payload.answer or not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Answer text is required.")
    return verify_answer(payload.answer)


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TRUTHLAYER_HOST", "0.0.0.0")
    port = int(os.getenv("TRUTHLAYER_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
