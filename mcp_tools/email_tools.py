from fastmcp import FastMCP

email_mcp = FastMCP("Email Tools")


@email_mcp.tool
def list_unread_emails() -> dict:
    """List unread emails."""
    return {"emails": []}