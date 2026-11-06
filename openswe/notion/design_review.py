"""The agent's review of a design document while it is in review.

A design entering review, or edited while in review, queues a review round once
the edits settle. The first round reviews the whole design; each later round
reviews only what changed since the version last reviewed, which is kept here.
The review only comments: approving the design stays a person's decision.
"""

import difflib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID, uuid7

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from openswe.database import postgres
from openswe.database.orm import NOW, Base
from openswe.input_messages import RunMessage, system_input, system_introduction
from openswe.jobs import queue
from openswe.notion.client import JsonObject, NotionClient, notion_client
from openswe.notion.context_index import ContextIndex
from openswe.notion.models import NotionComment, NotionPage
from openswe.notion.properties import (
    page_identifier,
    page_property,
    page_title,
    plain_text,
    relation_ids,
    status_name,
)
from openswe.notion.runs import NOTION_SYSTEM, CommentAuthors, NotionRun, Requester
from openswe.notion.settings import NotionSettings, normalize_notion_id, notion_settings
from openswe.prompts import prompt
from openswe.thread_ids import notion_page_thread_id
from openswe.threads.store import THREADS
from openswe.webhooks import common

logger = logging.getLogger(__name__)

REVIEW_JOB: Final = "notion_design_review"
DESIGN_REVIEW_KIND: Final = "design-review"
# A status change is a deliberate hand-off; content edits come in bursts.
ENTERED_REVIEW_SETTLE: Final = timedelta(minutes=1)
EDITED_SETTLE: Final = timedelta(minutes=10)
_BUSY_RETRY: Final = timedelta(minutes=5)
_MAX_DIFF_LINES: Final = 1500

ReviewOutcome = Literal["started", "not in review", "unchanged", "busy"]


class ReviewedDesign(Base):
    """The design text the agent last reviewed, so the next round reviews only changes."""

    __tablename__ = "notion_reviewed_design"

    notion_page_id: Mapped[str]
    reviewed_markdown: Mapped[str]
    id: Mapped[UUID] = mapped_column(primary_key=True, default_factory=uuid7)
    created_at: Mapped[datetime | None] = mapped_column(server_default=NOW, init=False)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=NOW, init=False)
    # Review rounds are queued by Notion webhooks, so no person is behind them.
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    @classmethod
    async def markdown_of(cls, page_id: str) -> str | None:
        async with postgres.session() as session:
            return await session.scalar(
                select(cls.reviewed_markdown).where(
                    cls.notion_page_id == normalize_notion_id(page_id)
                )
            )

    @classmethod
    async def record(cls, page_id: str, markdown: str) -> None:
        async with postgres.session() as session:
            await session.execute(
                insert(cls)
                .values(
                    id=uuid7(),
                    notion_page_id=normalize_notion_id(page_id),
                    reviewed_markdown=markdown,
                )
                .on_conflict_do_update(
                    index_elements=[cls.notion_page_id],
                    set_={"reviewed_markdown": markdown, "updated_at": func.clock_timestamp()},
                )
            )


@dataclass(frozen=True)
class DesignReview:
    """One review round of a design document, read as it stands now."""

    client: NotionClient
    settings: NotionSettings
    page: NotionPage

    @staticmethod
    async def schedule(page_id: str, *, settle: timedelta) -> None:
        """Queue a round ``settle`` from now; a round already queued waits for this one."""
        await queue.schedule(
            REVIEW_JOB,
            {"page_id": page_id},
            due_at=datetime.now(UTC) + settle,
            key=f"{REVIEW_JOB}:{normalize_notion_id(page_id)}",
        )

    @classmethod
    async def run(cls, page_id: str) -> ReviewOutcome:
        """Run the round queued for the design, reading it as it stands now."""
        async with notion_client() as client:
            page = await client.get_page(page_id)
            return await cls(client, notion_settings(), page).start()

    def in_review(self) -> bool:
        settings = self.settings
        if not settings.reviews_designs or not settings.design_tags:
            return False
        if status_name(self.page, settings.design_status_property) != settings.design_review_status:
            return False
        tags = page_property(self.page, settings.design_tag_property)
        names = {option.name for option in (tags.multi_select or [])} if tags else set()
        return bool(names & set(settings.design_tags))

    async def start(self) -> ReviewOutcome:
        """Send the round to the design's thread, unless nothing changed since the last."""
        if self.page.in_trash or not self.in_review():
            return "not in review"
        thread_id = notion_page_thread_id(self.page.id)
        thread = await THREADS.get(thread_id)
        if thread is not None and thread.status == "busy":
            # Starting now would interrupt the round still commenting.
            await self.schedule(self.page.id, settle=_BUSY_RETRY)
            return "busy"
        design = await self.client.get_page_markdown(self.page.id)
        previous = await ReviewedDesign.markdown_of(self.page.id)
        if previous is not None and previous.strip() == design.markdown.strip():
            return "unchanged"

        task = await self._task()
        author = self.page.created_by.id if self.page.created_by else None
        requester = await Requester.of(self.client, author)
        repo = await requester.repo_for(task or self.page, self.settings)
        if repo and not common.is_repo_allowed(repo):
            repo = None
        index = await ContextIndex.load(self.client, self.settings, design_id=self.page.id)
        review_prompt = prompt(
            "runs/notion-design-review",
            title=page_title(self.page) or "Untitled design",
            design_url=self.page.url,
            repository=f"{repo['owner']}/{repo['name']}" if repo else "",
            task=await self._task_text(task) if task else "",
            design=design.markdown or "(empty page)",
            truncated=design.truncated,
            diff=self._diff(previous, design.markdown) if previous is not None else "",
            discussions=await self._discussions(),
            documents=[entry.line() for entry in index.documents],
            designs=[entry.line() for entry in index.designs],
            adrs=[entry.line() for entry in index.adrs],
        )
        messages: list[RunMessage] = [
            system_introduction(NOTION_SYSTEM),
            system_input(
                review_prompt,
                {
                    "sender_id": NOTION_SYSTEM["id"],
                    "surface": "notion",
                    "kind": "system",
                    "data": {
                        "design": {"id": self.page.id, "url": self.page.url},
                        "round": "follow-up" if previous is not None else "first",
                    },
                },
            ),
        ]
        run = NotionRun(thread_id, self.page, requester, repo, kind=DESIGN_REVIEW_KIND)
        await run.start(messages)
        await ReviewedDesign.record(self.page.id, design.markdown)
        return "started"

    async def _task(self) -> NotionPage | None:
        """The task this design is linked from, if any."""
        relation: JsonObject = {
            "property": self.settings.design_property,
            "relation": {"contains": self.page.id},
        }
        for data_source_id in sorted(self.settings.task_data_source_ids):
            tasks = await self.client.query_data_source(data_source_id, relation, limit=1)
            if tasks:
                return tasks[0]
        return None

    async def _task_text(self, task: NotionPage) -> str:
        body = await self.client.get_page_markdown(task.id)
        heading = " ".join(part for part in (page_identifier(task), page_title(task)) if part)
        lines = [f"### {heading or 'Untitled task'}", f"URL: {task.url}"]
        status = status_name(task, self.settings.status_property)
        if status:
            lines.append(f"Status: {status}")
        linked = len(relation_ids(task, self.settings.design_property))
        if linked > 1:
            lines.append(f"The task links {linked} designs; this is one of them.")
        lines.extend(["", body.markdown or "(no description)"])
        return "\n".join(lines)

    @staticmethod
    def _diff(previous: str, current: str) -> str:
        lines = list(
            difflib.unified_diff(
                previous.splitlines(),
                current.splitlines(),
                "last reviewed",
                "now",
                lineterm="",
            )
        )
        if len(lines) > _MAX_DIFF_LINES:
            lines = [*lines[:_MAX_DIFF_LINES], "… (diff truncated; the full design follows)"]
        return "\n".join(lines)

    async def _discussions(self) -> list[str]:
        """The page's open comment discussions, each with its id, oldest first."""
        comments = await self.client.list_comments(self.page.id)
        threads: dict[str, list[NotionComment]] = {}
        for comment in comments:
            if plain_text(comment.rich_text):
                threads.setdefault(comment.discussion_id, []).append(comment)
        authors = CommentAuthors(self.client, self.settings)
        rendered: list[str] = []
        for discussion_id, items in threads.items():
            lines = [await authors.line(item) for item in items]
            rendered.append("\n".join([f"Discussion `{discussion_id}`:", *lines]))
        return rendered
