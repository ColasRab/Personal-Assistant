from fastmcp import FastMCP

email_mcp = FastMCP("Email Tools", mask_error_details=True)


@email_mcp.tool
def list_unread_emails() -> dict:
    """List unread emails."""
    return {"emails": []}
