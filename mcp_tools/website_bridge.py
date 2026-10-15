"""Fixed-destination website requests. The model never supplies a destination or token."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastmcp.exceptions import ToolError


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolError("The website integration redirected. Set WEBSITE_URL to its final canonical origin.")


def website_request(payload: dict | None = None) -> dict:
    base = os.environ.get("WEBSITE_URL", "").strip().rstrip("/")
    token = os.environ.get("WEBSITE_MCP_TOKEN", "").strip()
    parsed = urllib.parse.urlsplit(base)
    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not base or not token:
        raise ToolError("Configure WEBSITE_URL and WEBSITE_MCP_TOKEN on the MCP server first.")
    if (parsed.scheme != "https" and not (is_local and parsed.scheme == "http")) or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ToolError("WEBSITE_URL must be your website's canonical HTTPS origin, without a path.")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base}/api/integrations/linkedin",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.build_opener(NoRedirects()).open(request, timeout=25) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ToolError("The website response was too large. Review the queue in your admin page.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ToolError("The website returned an unexpected response.")
            return result
    except urllib.error.HTTPError as error:
        message = "The website could not complete the integration request."
        try:
            details = json.loads(error.read(4096))
            if isinstance(details, dict) and isinstance(details.get("error"), str):
                message = details["error"][:500]
        except (ValueError, UnicodeError):
            pass
        raise ToolError(f"{message} (HTTP {error.code})") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ToolError("The website integration is unreachable. Check its deployment and environment settings.") from None
    except (ValueError, UnicodeError):
        raise ToolError("The website returned invalid JSON. Check WEBSITE_URL and the deployed integration route.") from None
