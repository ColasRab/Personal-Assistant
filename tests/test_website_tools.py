import asyncio
import hashlib
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastmcp.exceptions import ToolError

from mcp_auth import HashedBearerVerifier, configured_auth
from mcp_tools.website_bridge import NoRedirects, website_request


class WebsiteToolTests(unittest.TestCase):
    def test_valid_bearer_required(self):
        digest = hashlib.sha256(b"test-secret").hexdigest()
        verifier = HashedBearerVerifier(digest)
        self.assertIsNotNone(asyncio.run(verifier.verify_token("test-secret")))
        self.assertIsNone(asyncio.run(verifier.verify_token("wrong-secret")))
        self.assertIsNone(asyncio.run(verifier.verify_token("")))

    def test_website_access_cannot_start_without_mcp_auth(self):
        with patch.dict(os.environ, {"WEBSITE_URL": "https://portfolio.example"}, clear=True):
            with self.assertRaises(RuntimeError):
                configured_auth()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(configured_auth())

    def test_invalid_hash_is_rejected(self):
        with patch.dict(os.environ, {"MCP_AUTH_TOKEN_SHA256": "plain-text"}, clear=True):
            with self.assertRaises(RuntimeError):
                configured_auth()

    def test_website_origin_is_fixed_and_validated(self):
        for url in ("http://portfolio.example", "https://person:password@portfolio.example", "https://portfolio.example/unexpected-path", "https://portfolio.example?destination=other"):
            with self.subTest(url=url), patch.dict(os.environ, {"WEBSITE_URL": url, "WEBSITE_MCP_TOKEN": "test-token"}, clear=True):
                with self.assertRaises(ToolError):
                    website_request()

    def test_bridge_only_sends_configured_secret_to_fixed_endpoint(self):
        response = MagicMock()
        response.read.return_value = json.dumps({"drafts": []}).encode()
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.dict(os.environ, {"WEBSITE_URL": "https://portfolio.example", "WEBSITE_MCP_TOKEN": "test-token"}, clear=True), patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(website_request(), {"drafts": []})
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://portfolio.example/api/integrations/linkedin")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(request.get_method(), "GET")

    def test_redirects_do_not_forward_integration_tokens(self):
        with self.assertRaises(ToolError):
            NoRedirects().redirect_request(None, None, 302, "Found", {}, "https://other.example")


if __name__ == "__main__":
    unittest.main()
