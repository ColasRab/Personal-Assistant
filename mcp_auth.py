"""Bearer authentication for the website-enabled MCP server."""

import hashlib
import hmac
import os
import re

from fastmcp.server.auth import AccessToken, TokenVerifier


class HashedBearerVerifier(TokenVerifier):
    def __init__(self, expected_hash: str):
        super().__init__()
        self.expected_hash = expected_hash

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or len(token) > 4096:
            return None
        actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual, self.expected_hash):
            return None
        return AccessToken(token=token, client_id="personal-assistant", scopes=[])


def configured_auth() -> TokenVerifier | None:
    expected_hash = os.environ.get("MCP_AUTH_TOKEN_SHA256", "").strip().lower()
    website_enabled = bool(os.environ.get("WEBSITE_URL") or os.environ.get("WEBSITE_MCP_TOKEN"))
    if not expected_hash:
        if website_enabled:
            raise RuntimeError("Set MCP_AUTH_TOKEN_SHA256 before enabling website tools.")
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("MCP_AUTH_TOKEN_SHA256 must be a SHA-256 hex digest.")
    return HashedBearerVerifier(expected_hash)
