import logging
from typing import TypedDict

from openswe.notion.client import NOTION_ERRORS, notion_client
from openswe.notion.notifications import post_notion_comment
from openswe.run_config import RunConfig

logger = logging.getLogger(__name__)

_MAX_COMMENT_CHARS = 8_000


class CommentResult(TypedDict, total=False):
    success: bool
    error: str


async def comment_on_notion_task(text: str, discussion_id: str = "") -> CommentResult:
    """Implement the `comment_on_notion_task` tool."""
    cfg = RunConfig.from_runtime()
    page = cfg.notion_page
    if cfg.source != "notion" or page is None or not page.id:
        return {"success": False, "error": "This run was not started from a Notion task"}
    body = text.strip()
    if not body:
        return {"success": False, "error": "Comment text cannot be empty"}
    if len(body) > _MAX_COMMENT_CHARS:
        return {
            "success": False,
            "error": f"Comment must be at most {_MAX_COMMENT_CHARS} characters",
        }
    discussion_id = discussion_id.strip()
    if discussion_id:
        try:
            async with notion_client() as client:
                on_page = await client.has_discussion(page.id, discussion_id)
        except NOTION_ERRORS as exc:
            logger.warning(
                "Could not read Notion discussions",
                extra={"notion_page_id": page.id, "error_type": type(exc).__name__},
            )
            return {"success": False, "error": "Could not read the page's discussions"}
        if not on_page:
            return {"success": False, "error": "No open discussion with that id on this page"}
    if not await post_notion_comment(
        page.id, body, discussion_id=discussion_id or page.discussion_id
    ):
        return {"success": False, "error": "Notion did not accept the comment"}
    return {"success": True}
