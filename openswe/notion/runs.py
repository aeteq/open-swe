"""Starting agent runs in the thread of a Notion page, and who they run for."""

import logging
from dataclasses import dataclass
from typing import Self

from openswe.input_messages import RunInput, RunMessage, SystemIdentity
from openswe.notion.client import NotionClient
from openswe.notion.models import NotionComment, NotionPage, NotionUser
from openswe.notion.properties import page_identifier, page_title, plain_text, repo_config
from openswe.notion.settings import NotionSettings
from openswe.source_context import NotionPageRef, SourceContext
from openswe.users import User
from openswe.webhooks import common

logger = logging.getLogger(__name__)

NOTION_SYSTEM: SystemIdentity = {
    "id": "system:notion-task",
    "display_name": "Notion task",
    "platform": "notion",
}


@dataclass(frozen=True)
class Requester:
    """The person a run acts for: whoever assigned, approved or asked."""

    notion_user_id: str | None
    name: str | None
    email: str | None
    github_login: str | None

    @classmethod
    async def of(cls, client: NotionClient, user_id: str | None) -> Self:
        user = await client.find_user(user_id)
        if user is not None and user.is_bot:
            return cls(notion_user_id=None, name=None, email=None, github_login=None)
        email = user.email if user else None
        login = await User.login_for_email(email) if email else None
        return cls(
            notion_user_id=user_id,
            name=user.name if user else None,
            email=email,
            github_login=login,
        )

    async def repo_for(self, page: NotionPage, settings: NotionSettings) -> dict[str, str] | None:
        """The page's repository, else this person's default, else the workspace's."""
        repo = repo_config(page, settings.repo_property, common.DEFAULT_REPO_OWNER)
        if repo:
            return repo
        if self.github_login:
            try:
                profile_repo = await common.get_profile_default_repo(self.github_login)
            except Exception:
                logger.exception(
                    "Failed to read dashboard default repo for Notion requester",
                    extra={"notion_page_id": page.id},
                )
                profile_repo = None
            if profile_repo:
                return profile_repo
        return (await common.get_workspace_settings()).default_repo


class CommentAuthors:
    """Who wrote each comment, reading each Notion user once."""

    def __init__(self, client: NotionClient, settings: NotionSettings) -> None:
        self._client = client
        self._settings = settings
        self._users: dict[str, NotionUser | None] = {}

    async def user(self, comment: NotionComment) -> NotionUser | None:
        # Comment authors are partial users; only the full user says whether it is a bot.
        author_id = comment.created_by.id if comment.created_by else ""
        if not author_id:
            return None
        if author_id not in self._users:
            self._users[author_id] = await self._client.find_user(author_id)
        return self._users[author_id]

    async def is_agent(self, comment: NotionComment) -> bool:
        """Whether the agent wrote it, as the integration or as its member."""
        author_id = comment.created_by.id if comment.created_by else ""
        if self._settings.is_agent_user(author_id):
            return True
        user = await self.user(comment)
        return user is not None and user.is_bot

    async def line(self, comment: NotionComment) -> str:
        """The comment as a transcript line, the agent's own written as "You"."""
        if await self.is_agent(comment):
            name = "You"
        else:
            user = await self.user(comment)
            name = (user.name if user else None) or "User"
        return f"- **{name}**: {plain_text(comment.rich_text)}"


@dataclass(frozen=True)
class NotionRun:
    """A run in the agent thread of a Notion page, on behalf of ``requester``.

    ``kind`` says why the page started it: empty for an assigned task, ``mention``
    for a question asked in a comment, ``design-review`` for a design in review.
    """

    thread_id: str
    page: NotionPage
    requester: Requester
    repo: dict[str, str] | None
    kind: str = ""
    discussion_id: str = ""

    def page_ref(self) -> dict[str, str]:
        ref = {
            "id": self.page.id,
            "identifier": page_identifier(self.page),
            "url": self.page.url,
            "title": page_title(self.page),
            "data_source_id": self.page.parent.data_source_id or "",
            "triggering_user_name": self.requester.name or "",
        }
        if self.kind:
            ref["kind"] = self.kind
        if self.discussion_id:
            ref["discussion_id"] = self.discussion_id
        return ref

    async def configurable(self) -> tuple[dict[str, object], str]:
        """The run's configuration and workspace, recording the thread's metadata."""
        notion_page = self.page_ref()
        workspace = await common.get_thread_workspace(
            self.thread_id
        ) or await common.workspace_for_repo_config(self.repo)
        configurable: dict[str, object] = {
            "notion_page": notion_page,
            "user_email": self.requester.email,
            "source": "notion",
            "workspace": workspace,
            "environment": workspace,
        }
        if self.repo:
            configurable["repo"] = self.repo
        else:
            # A question asked on a page that names no repository runs without one.
            configurable["repo_explicitly_none"] = True
        if self.requester.github_login:
            configurable["github_login"] = self.requester.github_login
        await common.upsert_agent_thread_metadata(
            self.thread_id,
            source="notion",
            repo_config=self.repo,
            github_login=self.requester.github_login or "",
            user_email=self.requester.email or "",
            title=" ".join(
                part for part in (notion_page["identifier"], notion_page["title"]) if part
            )
            or "Notion task",
            source_context=SourceContext(notion_page=NotionPageRef.model_validate(notion_page)),
            workspace=workspace,
        )
        return configurable, workspace

    async def start(
        self, messages: list[RunMessage], configurable: dict[str, object] | None = None
    ) -> None:
        """Send ``messages`` to the thread, configured by :meth:`configurable` unless given."""
        if configurable is None:
            configurable, _ = await self.configurable()
        run_input: RunInput = {"messages": messages}
        run = await common.dispatch_agent_run(
            self.thread_id,
            None,
            configurable,
            source="notion",
            thread_title=None,
            input=run_input,
            metadata=common.AGENT_VERSION_METADATA,
        )
        logger.info(
            "Dispatched Notion run",
            extra={
                "agent_thread_id": self.thread_id,
                "run_id": run.get("run_id") if isinstance(run, dict) else None,
                "notion_run_kind": self.kind or "task",
            },
        )
