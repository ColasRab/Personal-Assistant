"""Bounded, in-memory PDF intake. No URLs, arbitrary server paths, or retained PDFs."""

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from fastmcp.exceptions import ToolError

MAX_PDF_BYTES = 20 * 1024 * 1024
_parser_slot = threading.BoundedSemaphore(1)


def extract_pdf_context(pdf_base64: str, filename: str, start_page: int = 1, max_pages: int = 20) -> dict:
    if not isinstance(pdf_base64, str) or len(pdf_base64) > 4 * ((MAX_PDF_BYTES + 2) // 3):
        raise ToolError("Upload a PDF no larger than 20 MiB.")
    if not 1 <= start_page <= 2000 or not 1 <= max_pages <= 40:
        raise ToolError("start_page must be 1–2000 and max_pages must be 1–40.")
    try:
        raw = base64.b64decode(pdf_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ToolError("Supply plain base64 PDF bytes, not a file path, URL, or data URI.") from None
    return extract_pdf_bytes(raw, filename, start_page, max_pages)


def extract_pdf_bytes(raw: bytes, filename: str, start_page: int = 1, max_pages: int = 20) -> dict:
    """Raw-byte intake avoids base64 copies for direct browser uploads."""
    if not 1 <= start_page <= 2000 or not 1 <= max_pages <= 40:
        raise ToolError("start_page must be 1–2000 and max_pages must be 1–40.")
    if not isinstance(raw, bytes) or len(raw) > MAX_PDF_BYTES or not raw.startswith(b"%PDF-"):
        raise ToolError("Upload a valid PDF no larger than 20 MiB.")
    if not _parser_slot.acquire(blocking=False):
        raise ToolError("Another PDF is being processed. Try again when it finishes.")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("pdf_worker.py")), str(start_page), str(max_pages)],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=18, check=False,
            env={**{key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}},
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        raise ToolError("PDF parsing exceeded its time limit. Upload a simpler PDF or a smaller page range.") from None
    finally:
        _parser_slot.release()
    if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
        raise ToolError("PDF parsing stopped at its safety limit. Try a simpler PDF.")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError):
        raise ToolError("PDF parsing returned an invalid result.") from None
    if "error" in result:
        raise ToolError(result["error"])
    basename = str(filename).replace("\\", "/").split("/")[-1].strip()[:180] or "context.pdf"
    return {**result, "source_name": basename, "source_sha256": hashlib.sha256(raw).hexdigest(), "kind": "pdf"}
