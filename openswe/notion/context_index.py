"""The documents a design review checks a design against, listed by name and summary.

The review reads the summaries and opens in full only the pages that bear on the
design, through ``read_notion_page``.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Self

from pydantic import JsonValue

from openswe.notion.client import NOTION_ERRORS, NotionClient
from openswe.notion.models import NotionPage
from openswe.notion.properties import page_title, status_name, text_value
from openswe.notion.settings import NotionSettings, normalize_notion_id

logger = logging.getLogger(__name__)

_MAX_PAGES = 300
_SUMMARY_CHARS = 400
# Notion allows about three requests a second per integration.
_OPENING_READS = 3


@dataclass(frozen=True)
class ContextEntry:
    page_id: str
    title: str
    url: str
    summary: str

    def line(self) -> str:
        label = f"[{self.title}]({self.url})" if self.url else self.title
        summary = f": {self.summary}" if self.summary else ""
        return f"- {label} (id `{self.page_id}`){summary}"


@dataclass(frozen=True)
class ContextIndex:
    """Context documents in force, approved designs and accepted ADRs."""

    documents: list[ContextEntry]
    designs: list[ContextEntry]
    adrs: list[ContextEntry]

    @classmethod
    async def load(cls, client: NotionClient, settings: NotionSettings, *, design_id: str) -> Self:
        """Everything in force, except the design under review."""
        reader = _IndexReader(client, settings)
        documents, designs, adrs = await asyncio.gather(
            reader.documents(settings.context_tags, settings.context_statuses),
            reader.documents(settings.design_tags, frozenset({settings.design_approved_status})),
            reader.adrs(),
        )
        skipped = normalize_notion_id(design_id)
        designs = [page for page in designs if normalize_notion_id(page.id) != skipped]
        return cls(
            documents=await reader.entries(documents),
            designs=await reader.entries(designs),
            adrs=await reader.entries(adrs),
        )


class _IndexReader:
    """Reads one index, opening each page's text at most once."""

    def __init__(self, client: NotionClient, settings: NotionSettings) -> None:
        self._client = client
        self._settings = settings
        self._reads = asyncio.Semaphore(_OPENING_READS)

    async def documents(self, tags: tuple[str, ...], statuses: frozenset[str]) -> list[NotionPage]:
        settings = self._settings
        if not settings.documents_data_source_id or not tags or not statuses:
            return []
        tagged: list[JsonValue] = [
            {"property": settings.design_tag_property, "multi_select": {"contains": tag}}
            for tag in tags
        ]
        pages = await self._query(settings.documents_data_source_id, {"or": tagged})
        return [
            page for page in pages if status_name(page, settings.design_status_property) in statuses
        ]

    async def adrs(self) -> list[NotionPage]:
        settings = self._settings
        if not settings.adr_data_source_id:
            return []
        # Few enough to filter here, whether the status is a select or a status.
        pages = await self._query(settings.adr_data_source_id, None)
        return [
            page
            for page in pages
            if status_name(page, settings.adr_status_property) == settings.adr_accepted_status
        ]

    async def _query(
        self, data_source_id: str, filter_: dict[str, JsonValue] | None
    ) -> list[NotionPage]:
        try:
            pages = await self._client.query_data_source(data_source_id, filter_, limit=_MAX_PAGES)
        except NOTION_ERRORS as exc:
            logger.warning(
                "Could not list Notion context documents",
                extra={"notion_data_source_id": data_source_id, "error_type": type(exc).__name__},
            )
            return []
        return [page for page in pages if not page.in_trash]

    async def entries(self, pages: list[NotionPage]) -> list[ContextEntry]:
        return list(await asyncio.gather(*(self._entry(page) for page in pages)))

    async def _entry(self, page: NotionPage) -> ContextEntry:
        summary = text_value(page, self._settings.summary_property) or await self._opening(page)
        summary = " ".join(summary.split())
        if len(summary) > _SUMMARY_CHARS:
            summary = f"{summary[: _SUMMARY_CHARS - 1].rstrip()}…"
        return ContextEntry(
            page_id=page.id, title=page_title(page) or "Untitled", url=page.url, summary=summary
        )

    async def _opening(self, page: NotionPage) -> str:
        """The start of the page's text, for a page nobody summarized."""
        async with self._reads:
            try:
                markdown = (await self._client.get_page_markdown(page.id)).markdown
            except NOTION_ERRORS as exc:
                logger.warning(
                    "Could not read Notion context document",
                    extra={"notion_page_id": page.id, "error_type": type(exc).__name__},
                )
                return ""
        lines = (line.strip().lstrip("#>*- ").strip() for line in markdown.splitlines())
        return " ".join(line for line in lines if line and not line.startswith(("<", "---")))
