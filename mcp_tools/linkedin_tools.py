from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .website_bridge import website_request

linkedin_mcp = FastMCP("LinkedIn Tools", mask_error_details=True)


@linkedin_mcp.tool
def draft_linkedin_post(topic: str) -> dict:
    """Keep supplied LinkedIn copy as an unposted draft. Write the copy before calling this tool; it never publishes."""
    text = topic.strip()
    if not text or len(text) > 3000:
        raise ToolError("Supply draft text between 1 and 3,000 characters.")
    return {"commentary": text, "status": "draft", "requires_approval": True, "saved_to_website": False}


@linkedin_mcp.tool(annotations={"readOnlyHint": True})
def list_website_linkedin_drafts() -> dict:
    """Read pending website-to-LinkedIn drafts. The website administrator reviews and approves publication through Buffer; this tool cannot publish."""
    return website_request()


@linkedin_mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True})
def prepare_website_linkedin_draft(post_id: str) -> dict:
    """Queue one published website story for LinkedIn review, without posting. post_id is the story's Supabase UUID."""
    return website_request({"action": "prepare", "postId": post_id})


@linkedin_mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True})
def import_linkedin_item_to_website(
    url: str,
    title: str,
    body: str,
    author: str = "",
    mentioned: bool = False,
    category: str = "engagements",
) -> dict:
    """Import supplied LinkedIn text or a mention summary as a website DRAFT with source credit. Does not scrape LinkedIn or publish anything."""
    if category not in {"accomplishments", "personal_works", "professional_works", "engagements"}:
        raise ToolError("Choose a valid website category.")
    return website_request({
        "action": "import", "url": url, "title": title, "body": body, "author": author,
        "origin": "linkedin_mention" if mentioned else "linkedin_post", "category": category,
    })
