from fastmcp import FastMCP

linkedin_mcp = FastMCP("LinkedIn Tools")


@linkedin_mcp.tool
def draft_linkedin_post(topic: str) -> str:
    """Draft a LinkedIn post about a topic."""
    return f"Draft LinkedIn post about: {topic}"