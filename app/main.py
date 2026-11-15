from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import APP_NAME, OFFLINE_MODE, SAPHES_HOST, SAPHES_PORT
from app.services.ingest import extract_anything, extract_from_bytes
from app.services.verifier import verify_answer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_NAME, version="0.2.0")


class VerificationRequest(BaseModel):
    # `answer` accepts raw text or a URL; `url` is the explicit form.
    answer: str | None = None
    url: str | None = None
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
    raw = (payload.url or payload.answer or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Answer text is required.")
    ingested = extract_anything(raw)
    return verify_answer(raw, allow_live=payload.allow_live, ingest=ingested)


@app.post("/api/verify-file")
async def verify_file_endpoint(
    file: UploadFile = File(...),
    allow_live: bool | None = Form(None),
) -> dict:
    data = await file.read()
    ingested = extract_from_bytes(file.filename or "upload", data)
    return verify_answer(file.filename or "upload", allow_live=allow_live, ingest=ingested)


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=SAPHES_HOST, port=SAPHES_PORT, reload=True)
