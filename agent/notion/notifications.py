"""Best-effort writes back to a Notion task: comments, status and the PR link.

Each helper opens its own client, so it works from webhooks, tools and the
completion webhook alike. None of them raises: a Notion outage must not fail
the run or the tool that triggered the write.
"""

import logging

from pydantic import JsonValue

from agent.notion.client import NOTION_ERRORS, notion_client
from agent.notion.models import NotionDataSource, NotionPage
from agent.notion.properties import status_name, status_patch, url_patch
from agent.notion.settings import NotionSettings, notion_settings

logger = logging.getLogger(__name__)


async def post_notion_comment(page_id: str, body: str) -> bool:
    try:
        async with notion_client() as client:
            await client.create_comment(page_id, body)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Notion comment not delivered",
            extra={"notion_page_id": page_id, "error_type": type(exc).__name__},
        )
        return False
    return True


async def _schema(page: NotionPage) -> NotionDataSource | None:
    data_source_id = page.parent.data_source_id
    if not data_source_id:
        return None
    try:
        async with notion_client() as client:
            return await client.get_data_source(data_source_id)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Could not read Notion data source schema",
            extra={"notion_data_source_id": data_source_id, "error_type": type(exc).__name__},
        )
        return None


async def update_task_properties(page: NotionPage, properties: dict[str, JsonValue]) -> bool:
    if not properties:
        return False
    try:
        async with notion_client() as client:
            await client.update_page_properties(page.id, properties)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Notion task properties not updated",
            extra={
                "notion_page_id": page.id,
                "notion_properties": sorted(properties),
                "error_type": type(exc).__name__,
            },
        )
        return False
    return True


async def set_task_status(page: NotionPage, status: str, settings: NotionSettings) -> bool:
    if status_name(page, settings.status_property) == status:
        return True
    patch = status_patch(page, settings.status_property, status, await _schema(page))
    return await update_task_properties(page, patch or {})


async def record_pull_request(page_id: str, pr_url: str, *, announce: bool) -> None:
    """Link the PR on the task, move it to review, and (for a new PR) say so in a comment."""
    settings = notion_settings()
    try:
        async with notion_client() as client:
            page = await client.get_page(page_id)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Could not read Notion task to record its PR",
            extra={"notion_page_id": page_id, "error_type": type(exc).__name__},
        )
        return

    properties: dict[str, JsonValue] = dict(url_patch(page, settings.pr_property, pr_url) or {})
    # A task someone already moved past review keeps its status.
    if status_name(page, settings.status_property) in settings.startable_statuses:
        properties.update(
            status_patch(
                page, settings.status_property, settings.status_in_review, await _schema(page)
            )
            or {}
        )
    await update_task_properties(page, properties)
    if announce:
        await post_notion_comment(page_id, f"✅ Pull request opened: {pr_url}")
