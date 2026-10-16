"""Server-to-server PDF extraction for the website admin (never a public upload)."""

import hmac
import asyncio
import base64
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

from fastmcp.exceptions import ToolError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_tools.pdf_context import MAX_PDF_BYTES, extract_pdf_bytes, extract_pdf_context

MAX_ADMIN_PDF_BYTES = MAX_PDF_BYTES
MAX_BODY_BYTES = 4 * ((MAX_ADMIN_PDF_BYTES + 2) // 3) + 4096
_upload_slot = threading.BoundedSemaphore(1)


def sign_pdf_token(kind: str, payload: dict, secret: str) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
    message = f"{kind}.{encoded}"
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{message}.{signature}"


def verify_upload_token(token: str, secret: str, origin: str) -> dict:
    try:
        kind, encoded, signature = token.split(".")
        if kind != "pdf-upload-v1" or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", signature):
            raise ValueError()
        actual = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{kind}.{encoded}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(actual, signature):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(claims, dict) or type(claims.get("expires_at")) is not int or not time.time() < claims["expires_at"] <= time.time() + 600:
            raise ValueError()
        if claims.get("origin") != origin or not valid_origin(origin):
            raise ValueError()
        UUID(claims["owner"])
        if type(claims.get("size")) is not int or not 5 <= claims["size"] <= MAX_ADMIN_PDF_BYTES:
            raise ValueError()
        if not re.fullmatch(r"[0-9a-f]{64}", claims.get("sha256", "")):
            raise ValueError()
        for key in ("filename", "title"):
            if not isinstance(claims.get(key), str) or not 1 <= len(claims[key]) <= 180 or "\x00" in claims[key]:
                raise ValueError()
        if type(claims.get("start_page")) is not int or not 1 <= claims["start_page"] <= 2000 or type(claims.get("max_pages")) is not int or not 1 <= claims["max_pages"] <= 40:
            raise ValueError()
        return claims
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError("Invalid or expired PDF upload authorization.") from None


def valid_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return bool(len(origin) <= 512 and parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


async def direct_pdf(request: Request, claims: dict, secret: str) -> JSONResponse:
    if not _upload_slot.acquire(blocking=False):
        return JSONResponse({"error": "Another PDF is being uploaded. Try again when it finishes."}, status_code=429)
    try:
        chunks = []; size = 0
        async with asyncio.timeout(120):
            async for chunk in request.stream():
                size += len(chunk)
                if size > claims["size"] or size > MAX_ADMIN_PDF_BYTES:
                    return JSONResponse({"error": "Choose a PDF no larger than 20 MiB; its size must match the upload authorization."}, status_code=413)
                chunks.append(chunk)
        raw = b"".join(chunks)
        chunks.clear()
        if size != claims["size"] or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), claims["sha256"]):
            return JSONResponse({"error": "The file changed. Select it again and restart the upload."}, status_code=400)
        extracted = await run_in_threadpool(extract_pdf_bytes, raw, claims["filename"], claims["start_page"], claims["max_pages"])
        receipt = sign_pdf_token("pdf-context-v1", {"owner": claims["owner"], "expires_at": int(time.time()) + 600, "upload": claims, "extracted": extracted}, secret)
        return JSONResponse({"receipt": receipt}, headers={"Cache-Control": "no-store"})
    finally:
        _upload_slot.release()


async def _extract_admin_pdf(request: Request) -> JSONResponse:
    # Custom routes do not inherit MCP tool authentication. Authenticate explicitly.
    expected = os.environ.get("WEBSITE_MCP_TOKEN", "").strip()
    supplied = request.headers.get("authorization", "")
    if not expected or not os.environ.get("WEBSITE_URL"):
        return JSONResponse({"error": "Website PDF extraction is not configured."}, status_code=503)
    if len(supplied) > 4096:
        return JSONResponse({"error": "Unauthorized."}, status_code=401)
    if supplied.startswith("Bearer pdf-upload-v1."):
        try:
            claims = verify_upload_token(supplied[7:], expected, request.headers.get("origin", ""))
            return await direct_pdf(request, claims, expected)
        except ValueError:
            return JSONResponse({"error": "PDF upload authorization expired or is invalid. Restart the upload."}, status_code=401)
        except ToolError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except TimeoutError:
            return JSONResponse({"error": "The PDF upload timed out. Restart the upload."}, status_code=408)
        except Exception:
            return JSONResponse({"error": "PDF extraction failed. Try a smaller page range."}, status_code=500)
    if request.headers.get("origin") or not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
        return JSONResponse({"error": "Unauthorized."}, status_code=401)
    try:
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return JSONResponse({"error": "Choose a PDF no larger than 20 MiB."}, status_code=413)
            chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        if not isinstance(data, dict) or set(data) - {"pdf_base64", "filename", "start_page", "max_pages"}:
            raise ValueError()
        encoded = data.get("pdf_base64")
        filename = data.get("filename")
        start = data.get("start_page", 1)
        maximum = data.get("max_pages", 20)
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ADMIN_PDF_BYTES + 2) // 3):
            raise ValueError()
        if not isinstance(filename, str) or not filename or len(filename) > 180:
            raise ValueError()
        if type(start) is not int or type(maximum) is not int:
            raise ValueError()
        result = await run_in_threadpool(extract_pdf_context, encoded, filename, start, maximum)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError, UnicodeError):
        return JSONResponse({"error": "Send valid PDF bytes and a page range (1–40 pages)."}, status_code=400)
    except ToolError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception:
        # Never return parser internals or log document text/credentials.
        return JSONResponse({"error": "PDF extraction failed. Try a smaller page range."}, status_code=500)


async def extract_admin_pdf(request: Request) -> JSONResponse:
    origin = request.headers.get("origin", "")
    # Preflight grants no extraction access. POST still requires a signed, origin/file-bound token.
    if request.method == "OPTIONS":
        response = JSONResponse({}, status_code=200)
    else:
        response = await _extract_admin_pdf(request)
    if valid_origin(origin):
        response.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                                 "Access-Control-Allow-Methods": "POST, OPTIONS",
                                 "Access-Control-Allow-Headers": "Authorization, Content-Type",
                                 "Access-Control-Max-Age": "300"})
    return response
