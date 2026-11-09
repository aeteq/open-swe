import logging
from typing import TypedDict

from openswe.notion.client import NOTION_ERRORS, NotionAPIError, notion_client
from openswe.notion.properties import page_title
from openswe.notion.settings import page_id_from_reference
from openswe.run_config import RunConfig

logger = logging.getLogger(__name__)


class NotionPageResult(TypedDict, total=False):
    success: bool
    title: str
    url: str
    markdown: str
    truncated: bool
    error: str


async def read_notion_page(page: str) -> NotionPageResult:
    """Implement the `read_notion_page` tool."""
    if RunConfig.from_runtime().source != "notion":
        return {"success": False, "error": "This run was not started from Notion"}
    page_id = page_id_from_reference(page)
    if not page_id:
        return {"success": False, "error": "Give a Notion page id or URL"}
    try:
        async with notion_client() as client:
            found = await client.get_page(page_id)
            content = await client.get_page_markdown(page_id)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Could not read Notion page for the agent",
            extra={"notion_page_id": page_id, "error_type": type(exc).__name__},
        )
        if isinstance(exc, NotionAPIError) and exc.status_code == 404:  # noqa: PLR2004
            return {"success": False, "error": "No page with that id is shared with Open SWE"}
        return {"success": False, "error": "Could not read the page from Notion"}
    return {
        "success": True,
        "title": page_title(found),
        "url": found.url,
        "markdown": content.markdown,
        "truncated": content.truncated,
    }
