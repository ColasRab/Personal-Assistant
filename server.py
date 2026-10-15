import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_tools import email_mcp, linkedin_mcp

mcp = FastMCP("Personal Assistant")

mcp.mount(linkedin_mcp, namespace="linkedin")
mcp.mount(email_mcp, namespace="email")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_: Request) -> JSONResponse:
    """Health endpoint for container platforms."""
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
