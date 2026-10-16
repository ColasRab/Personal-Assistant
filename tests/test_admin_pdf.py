import base64
import hashlib
import os
from pathlib import Path
import unittest
import json
import time
from unittest.mock import patch

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from admin_pdf import extract_admin_pdf, MAX_BODY_BYTES, MAX_ADMIN_PDF_BYTES, sign_pdf_token
from mcp_auth import HashedBearerVerifier, configured_auth


class AdminPdfTests(unittest.TestCase):
    def setUp(self):
        # PDF extraction has no website callback, including for localhost admins.
        self.environment = patch.dict(os.environ, {"WEBSITE_MCP_TOKEN": "website-fixture", "WEBSITE_URL": ""})
        self.environment.start()
        # The custom endpoint has separate explicit auth, even with MCP bearer auth enabled.
        app = FastMCP("PDF test", auth=HashedBearerVerifier(hashlib.sha256(b"mcp-fixture").hexdigest()))
        app.custom_route("/admin/extract-pdf", methods=["POST", "OPTIONS"])(extract_admin_pdf)
        self.client = TestClient(app.http_app())
        self.payload = {"pdf_base64": base64.b64encode(b"%PDF-fixture").decode(), "filename": "source.pdf"}
        self.headers = {"Authorization": "Bearer website-fixture"}

    def tearDown(self):
        self.environment.stop()

    def test_custom_route_authenticates_before_reading_or_parsing_pdf(self):
        with patch("admin_pdf.extract_pdf_context") as parser:
            for token in [None, "Bearer wrong", "Bearer mcp-fixture"]:
                headers = {"Authorization": token} if token else {}
                self.assertEqual(self.client.post("/admin/extract-pdf", json=self.payload, headers=headers).status_code, 401)
            parser.assert_not_called()

    def test_docker_image_includes_the_admin_extractor_module(self):
        dockerfile = Path(__file__).parents[1].joinpath("Dockerfile").read_text()
        self.assertIn("COPY --chown=app:app admin_pdf.py ./", dockerfile)

    def test_valid_request_runs_bounded_extractor_without_model_or_website_writes(self):
        result = {"kind": "pdf", "pages": [{"page": 1, "text": "Evidence"}], "source_sha256": "digest"}
        with patch("admin_pdf.extract_pdf_context", return_value=result) as parser:
            response = self.client.post("/admin/extract-pdf", json=self.payload, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            self.assertEqual(response.headers["cache-control"], "no-store")
            parser.assert_called_once_with(self.payload["pdf_base64"], "source.pdf", 1, 20)

    def test_unconfigured_oversized_and_invalid_requests_fail_closed(self):
        for missing_token in ["", "   "]:
            with patch.dict(os.environ, {"WEBSITE_MCP_TOKEN": missing_token}), patch("admin_pdf.extract_pdf_context") as legacy_parser, patch("admin_pdf.extract_pdf_bytes") as direct_parser:
                response = self.client.post("/admin/extract-pdf", json=self.payload, headers=self.headers)
                self.assertEqual(response.status_code, 503)
                self.assertIn("WEBSITE_MCP_TOKEN", response.json()["error"])
                direct = self.client.post("/admin/extract-pdf", content=b"%PDF-fixture", headers=self.scoped_headers(b"%PDF-fixture"))
                self.assertEqual(direct.status_code, 503)
                legacy_parser.assert_not_called()
                direct_parser.assert_not_called()
        self.assertEqual(self.client.post("/admin/extract-pdf", content=b"x" * (MAX_BODY_BYTES + 1), headers=self.headers).status_code, 413)
        with patch("admin_pdf.extract_pdf_context") as parser:
            for extra in [{"url": "https://attacker.example"}, {"start_page": "1"}, {"max_pages": True}, {"filename": 123}, {"pdf_base64": 123}]:
                self.assertEqual(self.client.post("/admin/extract-pdf", json={**self.payload, **extra}, headers=self.headers).status_code, 400)
            parser.assert_not_called()

    def test_parser_errors_are_safe_and_never_include_internal_exception_details(self):
        with patch("admin_pdf.extract_pdf_context", side_effect=ToolError("Scanned PDF needs OCR.")):
            self.assertEqual(self.client.post("/admin/extract-pdf", json=self.payload, headers=self.headers).json()["error"], "Scanned PDF needs OCR.")
        with patch("admin_pdf.extract_pdf_context", side_effect=RuntimeError("PRIVATE INTERNAL SECRET")):
            response = self.client.post("/admin/extract-pdf", json=self.payload, headers=self.headers)
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("SECRET", response.text)

    def scoped_headers(self, raw, **overrides):
        claims = {"owner": "11111111-1111-4111-8111-111111111111", "origin": "https://website.example", "expires_at": int(time.time()) + 300,
                  "filename": "source.pdf", "title": "Evidence", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "start_page": 1, "max_pages": 20, **overrides}
        return {"Authorization": "Bearer " + sign_pdf_token("pdf-upload-v1", claims, "website-fixture"), "Origin": "https://website.example", "Content-Type": "application/pdf"}

    def test_direct_upload_accepts_exactly_20_mib_and_returns_a_signed_private_receipt(self):
        raw = b"%PDF-" + b" " * (MAX_ADMIN_PDF_BYTES - 5)
        extracted = {"kind": "pdf", "source_sha256": hashlib.sha256(raw).hexdigest(), "pages": [{"page": 1, "text": "Private evidence"}]}
        with patch("admin_pdf.extract_pdf_bytes", return_value=extracted) as parser:
            response = self.client.post("/admin/extract-pdf", content=raw, headers=self.scoped_headers(raw))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], "https://website.example")
            receipt = response.json()["receipt"]
            kind, encoded, _ = receipt.split(".")
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            self.assertEqual(kind, "pdf-context-v1")
            self.assertEqual(receipt, sign_pdf_token(kind, payload, "website-fixture"))
            self.assertEqual(payload["extracted"], extracted)
            self.assertNotIn("website-fixture", receipt)
            parser.assert_called_once_with(raw, "source.pdf", 1, 20)

    def test_direct_tokens_bind_file_size_digest_origin_owner_and_expiration(self):
        raw = b"%PDF-fixture"
        with patch("admin_pdf.extract_pdf_bytes") as parser:
            for change in [{"expires_at": 1}, {"owner": "bad"}, {"size": MAX_ADMIN_PDF_BYTES + 1}, {"origin": "https://attacker.example"}]:
                self.assertEqual(self.client.post("/admin/extract-pdf", content=raw, headers=self.scoped_headers(raw, **change)).status_code, 401)
            self.assertEqual(self.client.post("/admin/extract-pdf", content=raw, headers=self.scoped_headers(raw, sha256="0" * 64)).status_code, 400)
            self.assertEqual(self.client.post("/admin/extract-pdf", content=raw + b"x", headers=self.scoped_headers(raw)).status_code, 413)
            self.assertEqual(self.client.post("/admin/extract-pdf", content=raw, headers={**self.headers, "Origin": "https://website.example"}).status_code, 401)
            parser.assert_not_called()

    def test_browser_preflight_needs_no_secret_and_never_grants_extraction_by_itself(self):
        response = self.client.options("/admin/extract-pdf", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(self.client.post("/admin/extract-pdf", content=b"%PDF-fixture", headers={"Origin": "http://localhost:3000"}).status_code, 401)

    def test_localhost_upload_needs_no_website_url_and_preserves_origin_bound_auth(self):
        raw = b"%PDF-fixture"
        extracted = {"kind": "pdf", "source_sha256": hashlib.sha256(raw).hexdigest(), "pages": [{"page": 1, "text": "Synthetic localhost evidence"}]}
        for origin in ["http://localhost:3000", "http://127.0.0.1:3000"]:
            with self.subTest(origin=origin), patch.dict(os.environ, {}, clear=False), patch("admin_pdf.extract_pdf_bytes", return_value=extracted) as parser:
                os.environ.pop("WEBSITE_URL", None)
                headers = {**self.scoped_headers(raw, origin=origin), "Origin": origin}
                response = self.client.post("/admin/extract-pdf", content=raw, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertNotIn("access-control-allow-credentials", response.headers)
                kind, encoded, _ = response.json()["receipt"].split(".")
                payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                self.assertEqual(payload["extracted"], extracted)
                self.assertEqual(payload["upload"]["origin"], origin)
                self.assertEqual(response.json()["receipt"], sign_pdf_token(kind, payload, "website-fixture"))
                parser.assert_called_once_with(raw, "source.pdf", 1, 20)
                parser.reset_mock()
                wrong_origin = self.client.post("/admin/extract-pdf", content=raw, headers={**headers, "Origin": "http://localhost:3001"})
                self.assertEqual(wrong_origin.status_code, 401)
                for authorization in ["Bearer wrong", "Bearer mcp-fixture", "Bearer website-fixture"]:
                    denied = self.client.post("/admin/extract-pdf", content=raw, headers={**headers, "Authorization": authorization})
                    self.assertEqual(denied.status_code, 401)
                parser.assert_not_called()

    def test_pdf_only_configuration_still_requires_separate_mcp_authentication(self):
        with patch.dict(os.environ, {"MCP_AUTH_TOKEN_SHA256": ""}):
            with self.assertRaisesRegex(RuntimeError, "MCP_AUTH_TOKEN_SHA256"):
                configured_auth()
        digest = hashlib.sha256(b"mcp-fixture").hexdigest()
        with patch.dict(os.environ, {"MCP_AUTH_TOKEN_SHA256": digest}):
            verifier = configured_auth()
            self.assertIsInstance(verifier, HashedBearerVerifier)
            self.assertEqual(verifier.expected_hash, digest)

    def test_localhost_signed_upload_runs_the_real_pdf_parser_without_a_website_callback(self):
        from test_content_tools import pdf_bytes

        raw = pdf_bytes(text="Synthetic localhost PDF context.")
        origin = "http://localhost:3000"
        headers = {**self.scoped_headers(raw, origin=origin), "Origin": origin}
        with patch.dict(os.environ, {}, clear=False), patch("urllib.request.build_opener", side_effect=AssertionError("Extraction must not call the website")) as website_network:
            os.environ.pop("WEBSITE_URL", None)
            response = self.client.post("/admin/extract-pdf", content=raw, headers=headers)
            self.assertEqual(response.status_code, 200)
            website_network.assert_not_called()
        kind, encoded, _ = response.json()["receipt"].split(".")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        self.assertIn("Synthetic localhost PDF context.", payload["extracted"]["pages"][0]["text"])
        self.assertEqual(payload["extracted"]["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(response.json()["receipt"], sign_pdf_token(kind, payload, "website-fixture"))


if __name__ == "__main__":
    unittest.main()
