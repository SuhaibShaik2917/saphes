"""Input ingestion.

Stage 1 + 2 of the pipeline: figure out what was submitted, extract usable text
from it, and say so plainly when an input cannot be read.

Design rules:

* nothing here decides whether something is true - ingestion only extracts.
* every unsupported format returns an explicit limitation instead of silence.
* every extractor is bounded (bytes, characters, time) so a hostile or huge
  input cannot take the service down.
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any

import httpx

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
URL_TIMEOUT_SECONDS = 10

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".log", ".text"}
DATA_EXTENSIONS = {".json", ".xml", ".csv", ".tsv"}
WEB_EXTENSIONS = {".html", ".htm"}
DOC_EXTENSIONS = {".pdf", ".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".heic"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
SHEET_EXTENSIONS = {".xlsx", ".xls", ".pptx", ".ppt"}

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


@dataclass
class IngestResult:
    text: str = ""
    kind: str = "text"
    source_ref: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


def looks_like_url(value: str) -> bool:
    return bool(_URL_RE.match(value.strip()))


def detect_kind(name: str = "", text: str = "") -> str:
    if text and looks_like_url(text) and not name:
        return "url"
    suffix = Path(name).suffix.lower() if name else ""
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in DATA_EXTENSIONS:
        return {".json": "json", ".xml": "xml", ".csv": "csv", ".tsv": "csv"}[suffix]
    if suffix in WEB_EXTENSIONS:
        return "html"
    if suffix in DOC_EXTENSIONS:
        return suffix.lstrip(".")
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in SHEET_EXTENSIONS:
        return "spreadsheet"
    if suffix:
        return "unknown"
    return "text"


# --------------------------------------------------------------------------- #
# text helpers
# --------------------------------------------------------------------------- #

def _clip(text: str) -> tuple[str, list[str]]:
    text = re.sub(r"\s+\n", "\n", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], [
            f"Input truncated to the first {MAX_TEXT_CHARS:,} characters; the remainder was not verified."
        ]
    return text, []


def html_to_text(raw: str) -> tuple[str, str]:
    """Return (visible text, page title) from an HTML document."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else ""

    # Chrome (navigation, sidebars, cookie banners, footers) is not content:
    # keeping it floods claim extraction with link labels like "Follow us".
    body = re.sub(
        r"<(script|style|noscript|svg|template|nav|header|footer|aside|form|button)[^>]*>.*?</\1>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
    # Prefer the main/article region when a page marks one up.
    main = re.search(r"<(main|article)[^>]*>(.*?)</\1>", body, re.IGNORECASE | re.DOTALL)
    if main and len(re.sub(r"<[^>]+>", " ", main.group(2)).strip()) > 200:
        body = main.group(2)
    body = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)
    text = unescape(body)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    # Drop fragments that are only labels: too short to assert anything.
    lines = [line.strip() for line in text.splitlines()]
    kept = [line for line in lines if len(line) >= 40 or line.endswith((".", "!", "?"))]
    text = "\n".join(kept) if kept else "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), title


# --------------------------------------------------------------------------- #
# extractors
# --------------------------------------------------------------------------- #

def _extract_docx(data: bytes) -> tuple[str, dict[str, Any], list[str]]:
    meta: dict[str, Any] = {}
    limitations: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return "", meta, ["This file is not a readable .docx archive; no text was extracted."]

    try:
        root = ET.fromstring(xml_bytes)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs: list[str] = []
        for paragraph in root.iter(f"{ns}p"):
            chunk = "".join(node.text or "" for node in paragraph.iter(f"{ns}t"))
            if chunk.strip():
                paragraphs.append(chunk.strip())
        text = "\n".join(paragraphs)
        meta["paragraphs"] = len(paragraphs)
        if not text:
            limitations.append("The document contained no extractable paragraph text.")
        return text, meta, limitations
    except ET.ParseError:
        return "", meta, ["The .docx body could not be parsed as XML."]


def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any], list[str]]:
    meta: dict[str, Any] = {}
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return "", meta, [
            "PDF extraction needs the pypdf package (pip install pypdf). "
            "The file was received but its text was not read."
        ]

    try:
        reader = PdfReader(io.BytesIO(data))
        meta["pages"] = len(reader.pages)
        pages = [(page.extract_text() or "") for page in reader.pages[:40]]
        text = "\n".join(pages).strip()
        limitations: list[str] = []
        if len(reader.pages) > 40:
            limitations.append("Only the first 40 pages were read.")
        if not text:
            limitations.append(
                "No selectable text was found in this PDF - it is probably a scan. "
                "OCR is not bundled, so the images inside were not read."
            )
        return text, meta, limitations
    except Exception as exc:  # malformed or encrypted PDF
        return "", meta, [f"PDF could not be read ({type(exc).__name__})."]


def _extract_json(raw: str) -> tuple[str, dict[str, Any], list[str]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return raw, {}, [f"Invalid JSON ({exc.msg}); the raw text was used instead."]

    lines: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node[:50]):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, (str, int, float, bool)):
            lines.append(f"{path}: {node}")

    walk(payload, "")
    meta = {"keys": len(lines)}
    limitations = ["JSON values were flattened into key/value statements."]
    return "\n".join(lines), meta, limitations


def _extract_xml(raw: str) -> tuple[str, dict[str, Any], list[str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return raw, {}, [f"Invalid XML ({exc}); the raw text was used instead."]
    lines = [f"{element.tag}: {(element.text or '').strip()}"
             for element in root.iter() if (element.text or "").strip()]
    return "\n".join(lines), {"elements": len(lines)}, [
        "XML content was flattened into tag statements."
    ]


def _extract_csv(raw: str) -> tuple[str, dict[str, Any], list[str]]:
    try:
        dialect = csv.Sniffer().sniff(raw[:2000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    if not rows:
        return "", {}, ["The CSV file was empty."]

    header = [cell.strip() for cell in rows[0]]
    lines: list[str] = []
    for row in rows[1:60]:
        pairs = []
        for index, cell in enumerate(row):
            cell = cell.strip()
            if not cell:
                continue
            label = header[index] if index < len(header) and header[index] else f"column {index + 1}"
            pairs.append(f"{label} is {cell}")
        if pairs:
            lines.append("; ".join(pairs))
    limitations = []
    if len(rows) > 61:
        limitations.append(f"Only the first 60 of {len(rows) - 1} data rows were read.")
    return "\n".join(lines), {"rows": len(rows) - 1, "columns": len(header)}, limitations


def _unsupported(kind: str) -> list[str]:
    return {
        "image": [
            "Images need an OCR engine to become text, and none is bundled with this build. "
            "Paste the text from the image instead - the verdict engine itself is unaffected."
        ],
        "audio": [
            "Audio needs a transcription engine (for example Whisper) and none is bundled. "
            "Transcribe the clip, then paste the text."
        ],
        "video": [
            "Video needs transcription plus frame analysis, neither of which is bundled. "
            "Submit the transcript or the text shown on screen."
        ],
        "spreadsheet": [
            "Spreadsheet and presentation formats (.xlsx/.pptx) are not parsed in this build. "
            "Export the sheet to CSV, or paste the rows as text."
        ],
    }.get(kind, [f"'{kind}' inputs are not supported by this build."])


def extract_from_text(raw: str) -> IngestResult:
    text, limitations = _clip(raw)
    return IngestResult(text=text, kind="text", meta={"chars": len(text)}, limitations=limitations)


def extract_from_url(url: str) -> IngestResult:
    """Fetch a public page and return its visible text."""
    if not looks_like_url(url):
        return IngestResult(kind="url", limitations=["That does not look like an http(s) URL."])

    try:
        with httpx.Client(timeout=URL_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Saphes/0.3 (verification demo)"})
    except httpx.TimeoutException:
        return IngestResult(kind="url", source_ref=url,
                            limitations=["The page did not respond within 10 seconds."])
    except Exception as exc:
        return IngestResult(kind="url", source_ref=url,
                            limitations=[f"The page could not be fetched ({type(exc).__name__})."])

    if response.status_code >= 400:
        return IngestResult(kind="url", source_ref=url,
                            limitations=[f"The page returned HTTP {response.status_code}."])

    content_type = response.headers.get("content-type", "")
    if "application/pdf" in content_type:
        text, meta, limitations = _extract_pdf(response.content)
        return IngestResult(text=text, kind="pdf", source_ref=url, meta=meta, limitations=limitations)

    if "html" not in content_type and "text" not in content_type:
        return IngestResult(kind="unknown", source_ref=url, limitations=[
            f"That URL returned '{content_type or 'unknown content'}', which is not text."
        ])

    text, title = html_to_text(response.text)
    text, limitations = _clip(text)
    meta = {"title": title, "chars": len(text)}
    if not text:
        limitations.append("The page contained no readable text (it may be JavaScript-rendered).")
    return IngestResult(text=text, kind="url", source_ref=url, meta=meta, limitations=limitations)


def extract_from_bytes(name: str, data: bytes) -> IngestResult:
    kind = detect_kind(name=name)
    limitations: list[str] = []

    if len(data) > MAX_UPLOAD_BYTES:
        return IngestResult(kind=kind, limitations=[
            f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB and was not processed."
        ])

    if kind in {"image", "audio", "video", "spreadsheet", "unknown"}:
        return IngestResult(kind=kind, limitations=_unsupported(kind))

    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw = data.decode("latin-1")
            limitations.append("The file was not valid UTF-8; it was read as Latin-1.")
        except Exception:
            raw = ""

    meta: dict[str, Any] = {"bytes": len(data)}

    if kind == "docx":
        text, extra, more = _extract_docx(data)
        meta.update(extra)
        limitations.extend(more)
    elif kind == "pdf":
        text, extra, more = _extract_pdf(data)
        meta.update(extra)
        limitations.extend(more)
    elif kind == "json":
        text, extra, more = _extract_json(raw)
        meta.update(extra)
        limitations.extend(more)
    elif kind == "xml":
        text, extra, more = _extract_xml(raw)
        meta.update(extra)
        limitations.extend(more)
    elif kind == "csv":
        text, extra, more = _extract_csv(raw)
        meta.update(extra)
        limitations.extend(more)
    elif kind == "html":
        text, title = html_to_text(raw)
        meta["title"] = title
    else:
        text = raw

    text, more = _clip(text)
    limitations.extend(more)
    if not text.strip() and not limitations:
        limitations.append("No text could be extracted from this file.")

    return IngestResult(text=text, kind=kind, meta=meta, limitations=limitations)


def extract_anything(payload: str) -> IngestResult:
    """Entry point used by the API: a URL, or raw text."""
    value = (payload or "").strip()
    if not value:
        return IngestResult(limitations=["No input was provided."])
    if looks_like_url(value):
        return extract_from_url(value)
    return extract_from_text(value)
