"""Turn Notion webhook events into agent runs.

Notion events carry only ids, so every handler re-reads the page it is about.
Assignment and design approval share :func:`evaluate_task`, so both paths
apply the same assignee, status, repository and design checks.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, cast

import httpx2
from langchain_core.messages.content import create_text_block
from langgraph_sdk import get_client
from pydantic import JsonValue

from agent.input_messages import (
    PersonIdentity,
    RunInput,
    RunMessage,
    SystemIdentity,
    human_input,
    person_introduction,
    system_input,
    system_introduction,
)
from agent.notion.blocks import render_page_body
from agent.notion.client import NOTION_ERRORS, NotionClient, notion_client
from agent.notion.design_gate import DesignDoc, gate_comment, linked_designs, unapproved
from agent.notion.models import NotionComment, NotionPage, NotionUser, WebhookEvent
from agent.notion.notifications import post_notion_comment, set_task_status
from agent.notion.pending import forget_assigner, pending_assigner, remember_assigner
from agent.notion.properties import (
    date_text,
    page_identifier,
    page_title,
    people_ids,
    plain_text,
    property_was_updated,
    relation_ids,
    repo_config,
    status_name,
    text_value,
)
from agent.notion.settings import NotionSettings, normalize_notion_id, notion_settings
from agent.prompts import render_prompt
from agent.source_context import NotionPageRef, SourceContext
from agent.thread_ids import notion_page_thread_id
from agent.users import User
from agent.webhooks import common

logger = logging.getLogger(__name__)

TaskOutcome = Literal["dispatched", "followed_up", "blocked", "ignored"]

_SYSTEM: SystemIdentity = {
    "id": "system:notion-task",
    "display_name": "Notion task",
    "platform": "notion",
}
_MAX_RELATED_TITLES = 10
_MAX_CONTEXT_COMMENTS = 30
_SKIPPED_SUMMARY_TYPES = frozenset(
    {
        "title",
        "people",
        "unique_id",
        "url",
        "created_by",
        "last_edited_by",
        "created_time",
        "last_edited_time",
        "formula",
        "rollup",
        "files",
        "button",
    }
)


@dataclass(frozen=True)
class TaskResult:
    outcome: TaskOutcome
    reason: str


@dataclass(frozen=True)
class Requester:
    notion_user_id: str | None
    name: str | None
    email: str | None
    github_login: str | None


def _ignored(reason: str, page_id: str) -> TaskResult:
    logger.info("Notion task not started", extra={"notion_page_id": page_id, "reason": reason})
    return TaskResult("ignored", reason)


async def _person(client: NotionClient, user_id: str | None) -> NotionUser | None:
    if not user_id:
        return None
    try:
        return await client.get_user(user_id)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Could not read Notion user",
            extra={"notion_user_id": user_id, "error_type": type(exc).__name__},
        )
        return None


async def _requester(client: NotionClient, user_id: str | None) -> Requester:
    user = await _person(client, user_id)
    if user is not None and user.is_bot:
        return Requester(notion_user_id=None, name=None, email=None, github_login=None)
    email = user.email if user else None
    login = await User.login_for_email(email) if email else None
    return Requester(
        notion_user_id=user_id,
        name=user.name if user else None,
        email=email,
        github_login=login,
    )


async def _resolve_repo(
    page: NotionPage, settings: NotionSettings, requester: Requester
) -> dict[str, str] | None:
    repo = repo_config(page, settings.repo_property, common.DEFAULT_REPO_OWNER)
    if repo:
        return repo
    if requester.github_login:
        try:
            profile_repo = await common.get_profile_default_repo(requester.github_login)
        except Exception:
            logger.exception(
                "Failed to read dashboard default repo for Notion requester",
                extra={"notion_page_id": page.id},
            )
            profile_repo = None
        if profile_repo:
            return profile_repo
    return (await common.get_workspace_settings()).default_repo


async def _thread_busy(thread_id: str) -> bool:
    try:
        thread = await get_client(url=common.LANGGRAPH_URL).threads.get(thread_id)
    except Exception as exc:
        if common.is_not_found_error(exc):
            return False
        logger.warning("Could not read agent thread status", extra={"agent_thread_id": thread_id})
        return False
    return isinstance(thread, dict) and thread.get("status") == "busy"


async def evaluate_task(
    client: NotionClient,
    page: NotionPage,
    settings: NotionSettings,
    *,
    assigner_id: str | None,
    approved_design: DesignDoc | None = None,
) -> TaskResult:
    """Start, continue, or gate a task that may be assigned to the agent."""
    if not people_ids(page, settings.assignee_property) & settings.agent_user_ids:
        return _ignored("not assigned to the agent", page.id)
    status = status_name(page, settings.status_property)
    if status is not None and status not in settings.startable_statuses:
        return _ignored("status is not startable", page.id)

    thread_id = notion_page_thread_id(page.id)
    if approved_design is None and await _thread_busy(thread_id):
        return _ignored("task is already being worked on", page.id)

    if not assigner_id:
        assigner_id = await pending_assigner(page.id)
    if not assigner_id and page.created_by:
        assigner_id = page.created_by.id
    requester = await _requester(client, assigner_id)

    identifier = page_identifier(page)
    repo = await _resolve_repo(page, settings, requester)
    if not repo:
        await post_notion_comment(
            page.id,
            f"⚠️ Can't start {identifier or 'this task'}: set its {settings.repo_property} "
            "property to the GitHub repository to work in, then assign it again.",
        )
        return _ignored("no repository", page.id)
    if not common.is_repo_allowed(repo):
        await post_notion_comment(
            page.id,
            f"⚠️ Can't start {identifier or 'this task'}: {repo['owner']}/{repo['name']} "
            "is not a repository Open SWE is allowed to work in.",
        )
        return _ignored("repository not allowed", page.id)

    designs = await linked_designs(client, relation_ids(page, settings.design_property), settings)
    blocked_by = unapproved(designs, settings)
    if blocked_by:
        if assigner_id:
            await remember_assigner(page.id, assigner_id)
        await post_notion_comment(
            page.id, gate_comment(identifier, blocked_by, settings.design_approved_status)
        )
        logger.info(
            "Notion task waiting on design approval",
            extra={"notion_page_id": page.id, "blocked_design_count": len(blocked_by)},
        )
        return TaskResult("blocked", "design not approved")

    if approved_design is not None and await common.thread_exists(thread_id):
        await _dispatch_design_follow_up(page, repo, requester, approved_design, settings)
        outcome: TaskOutcome = "followed_up"
    else:
        await process_notion_task(client, page, repo, requester, designs, settings)
        outcome = "dispatched"
    await forget_assigner(page.id)
    return TaskResult(outcome, "started")


def _page_ref(page: NotionPage, requester: Requester) -> dict[str, str]:
    return {
        "id": page.id,
        "identifier": page_identifier(page),
        "url": page.url,
        "title": page_title(page),
        "data_source_id": page.parent.data_source_id or "",
        "triggering_user_name": requester.name or "",
    }


async def _configurable(
    thread_id: str,
    notion_page: dict[str, str],
    repo: dict[str, str],
    requester: Requester,
) -> tuple[dict[str, object], str]:
    workspace = await common.get_thread_workspace(
        thread_id
    ) or await common.workspace_for_repo_config(repo)
    configurable: dict[str, object] = {
        "repo": repo,
        "notion_page": notion_page,
        "user_email": requester.email,
        "source": "notion",
        "workspace": workspace,
        "environment": workspace,
    }
    if requester.github_login:
        configurable["github_login"] = requester.github_login
    await common.upsert_agent_thread_metadata(
        thread_id,
        source="notion",
        repo_config=repo,
        github_login=requester.github_login or "",
        user_email=requester.email or "",
        title=" ".join(part for part in (notion_page["identifier"], notion_page["title"]) if part)
        or "Notion task",
        source_context=SourceContext(notion_page=NotionPageRef.model_validate(notion_page)),
        workspace=workspace,
    )
    return configurable, workspace


def _person_identity(user: NotionUser) -> PersonIdentity:
    person: PersonIdentity = {"id": f"notion:{normalize_notion_id(user.id)}", "platform": "notion"}
    if user.name:
        person["display_name"] = user.name
    if user.email:
        person["email"] = user.email
    return person


async def _related_titles(client: NotionClient, page_ids: list[str]) -> list[str]:
    async def title(page_id: str) -> str | None:
        try:
            related = await client.get_page(page_id)
        except NOTION_ERRORS as exc:
            logger.warning(
                "Could not read related Notion page",
                extra={"notion_page_id": page_id, "error_type": type(exc).__name__},
            )
            return None
        name = page_title(related) or "Untitled"
        return f"[{name}]({related.url})" if related.url else name

    titles = await asyncio.gather(*(title(page_id) for page_id in page_ids[:_MAX_RELATED_TITLES]))
    return [value for value in titles if value]


async def _property_lines(
    client: NotionClient, page: NotionPage, designs: list[DesignDoc], settings: NotionSettings
) -> list[str]:
    skipped_names = {settings.assignee_property, settings.repo_property, settings.pr_property}
    lines: list[str] = []
    for name, prop in page.properties.items():
        if name in skipped_names or prop.type in _SKIPPED_SUMMARY_TYPES:
            continue
        if name == settings.design_property:
            value = "; ".join(
                f"{doc.markdown_link()} ({doc.status or 'unknown'})" for doc in designs
            )
        elif prop.type == "relation":
            value = "; ".join(await _related_titles(client, relation_ids(page, name)))
        elif prop.type == "date":
            value = date_text(page, name)
        elif prop.type == "status":
            value = status_name(page, name) or ""
        elif prop.type == "multi_select":
            value = ", ".join(option.name for option in prop.multi_select or [])
        elif prop.type == "checkbox":
            value = "yes" if prop.checkbox else "no"
        else:
            value = text_value(page, name)
        if value:
            lines.append(f"- {name}: {value}")
    return lines


def _comment_text(comment: NotionComment) -> str:
    return plain_text(comment.rich_text)


async def _context_comments(client: NotionClient, page: NotionPage) -> str:
    try:
        comments = await client.list_comments(page.id)
    except NOTION_ERRORS as exc:
        logger.warning(
            "Could not read Notion task comments",
            extra={"notion_page_id": page.id, "error_type": type(exc).__name__},
        )
        return ""
    # Comment authors are partial users; only the full user says whether it is a bot.
    authors: dict[str, NotionUser | None] = {}
    lines: list[str] = []
    for comment in comments[-_MAX_CONTEXT_COMMENTS:]:
        text = _comment_text(comment)
        author_id = comment.created_by.id if comment.created_by else ""
        if not text or not author_id:
            continue
        if author_id not in authors:
            authors[author_id] = await _person(client, author_id)
        author = authors[author_id]
        if author is not None and author.is_bot:
            continue
        lines.append(f"- **{(author.name if author else None) or 'User'}**: {text}")
    return "\n".join(["", "## Comments:", *lines]) if lines else ""


async def _image_blocks(
    image_urls: list[str], requester: Requester, workspace: str
) -> tuple[list[dict[str, object]], tuple[str, str] | None]:
    if not image_urls:
        return [], None
    override: tuple[str, str] | None = None
    model_id = await common.resolve_agent_model_id(requester.github_login, workspace=workspace)
    if not common.model_supports_images(model_id):
        override = common.default_vision_model_pair()
    blocks: list[dict[str, object]] = []
    async with httpx2.AsyncClient(timeout=common.DEFAULT_HTTP_TIMEOUT) as http:
        for url in common.dedupe_urls(image_urls):
            block = await common.fetch_image_block(url, http)
            if block:
                blocks.append(cast(dict[str, object], block))
    return blocks, override if blocks else None


async def process_notion_task(
    client: NotionClient,
    page: NotionPage,
    repo: dict[str, str],
    requester: Requester,
    designs: list[DesignDoc],
    settings: NotionSettings,
) -> None:
    """Start the agent on a task, with its body, properties and comments as the prompt."""
    thread_id = notion_page_thread_id(page.id)
    notion_page = _page_ref(page, requester)
    body = await render_page_body(client, page.id)
    property_lines = await _property_lines(client, page, designs, settings)
    comments = await _context_comments(client, page)

    prompt = render_prompt(
        "runs/notion-task.md",
        repository=f"{repo['owner']}/{repo['name']}",
        title=notion_page["title"] or "Untitled task",
        triggered_by_line=f"## Triggered by: {requester.name}\n\n" if requester.name else "",
        identifier=notion_page["identifier"] or "(no ID)",
        page_id=page.id,
        task_url_line=f"## Notion Task URL: {page.url}\n\n" if page.url else "",
        properties="## Properties:\n" + "\n".join(property_lines) + "\n\n"
        if property_lines
        else "",
        body=body.markdown or "No description",
        comments=comments,
    )

    configurable, workspace = await _configurable(thread_id, notion_page, repo, requester)
    image_blocks, model_override = await _image_blocks(body.image_urls, requester, workspace)
    if model_override:
        configurable["agent_model_id"], configurable["agent_effort"] = model_override

    content: str | list[dict[str, object]] = (
        [cast(dict[str, object], create_text_block(prompt)), *image_blocks]
        if image_blocks
        else prompt
    )
    messages: list[RunMessage] = [
        system_introduction(_SYSTEM),
        system_input(
            content,
            {
                "sender_id": _SYSTEM["id"],
                "surface": "notion",
                "kind": "system",
                "data": {
                    "task": {
                        "id": page.id,
                        "identifier": notion_page["identifier"],
                        "url": page.url,
                        "repository": f"{repo['owner']}/{repo['name']}",
                        "title": notion_page["title"],
                    }
                },
            },
        ),
    ]
    await _dispatch(thread_id, configurable, messages)
    await set_task_status(page, settings.status_in_progress, settings)


async def _dispatch_design_follow_up(
    page: NotionPage,
    repo: dict[str, str],
    requester: Requester,
    design: DesignDoc,
    settings: NotionSettings,
) -> None:
    thread_id = notion_page_thread_id(page.id)
    notion_page = _page_ref(page, requester)
    configurable, _ = await _configurable(thread_id, notion_page, repo, requester)
    prompt = render_prompt(
        "runs/notion-design-approved.md",
        design=design.markdown_link(),
        identifier=notion_page["identifier"] or notion_page["title"] or "this task",
        approved_status=settings.design_approved_status,
    )
    messages: list[RunMessage] = [
        system_introduction(_SYSTEM),
        system_input(
            prompt,
            {
                "sender_id": _SYSTEM["id"],
                "surface": "notion",
                "kind": "system",
                "data": {"design": {"id": design.id, "url": design.url}},
            },
        ),
    ]
    await _dispatch(thread_id, configurable, messages)
    await set_task_status(page, settings.status_in_progress, settings)


async def _dispatch(
    thread_id: str, configurable: dict[str, object], messages: list[RunMessage]
) -> None:
    run_input: RunInput = {"messages": messages}
    run = await common.dispatch_agent_run(
        thread_id,
        None,
        configurable,
        source="notion",
        input=run_input,
        metadata=common.AGENT_VERSION_METADATA,
    )
    logger.info(
        "Dispatched Notion task run",
        extra={
            "agent_thread_id": thread_id,
            "run_id": run.get("run_id") if isinstance(run, dict) else None,
        },
    )


async def _handle_task_page(
    client: NotionClient, event: WebhookEvent, page: NotionPage, settings: NotionSettings
) -> TaskResult:
    if event.type == "page.properties_updated" and not property_was_updated(
        page, settings.assignee_property, event.data.updated_properties
    ):
        return _ignored("assignee unchanged", page.id)
    return await evaluate_task(client, page, settings, assigner_id=event.person_author_id)


async def _handle_design_page(
    client: NotionClient, event: WebhookEvent, page: NotionPage, settings: NotionSettings
) -> list[TaskResult]:
    if event.type != "page.properties_updated" or not property_was_updated(
        page, settings.design_status_property, event.data.updated_properties
    ):
        return []
    if status_name(page, settings.design_status_property) != settings.design_approved_status:
        return []
    design = DesignDoc(
        id=page.id,
        title=page_title(page),
        url=page.url,
        status=settings.design_approved_status,
    )
    assignee_filters: list[JsonValue] = [
        {"property": settings.assignee_property, "people": {"contains": user_id}}
        for user_id in sorted(settings.agent_user_ids)
    ]
    results: list[TaskResult] = []
    for data_source_id in sorted(settings.task_data_source_ids):
        tasks = await client.query_data_source(
            data_source_id,
            {
                "and": [
                    {"property": settings.design_property, "relation": {"contains": page.id}},
                    {"or": assignee_filters},
                ]
            },
        )
        for task in tasks:
            results.append(
                await evaluate_task(
                    client, task, settings, assigner_id=None, approved_design=design
                )
            )
    return results


async def _handle_comment(
    client: NotionClient, event: WebhookEvent, settings: NotionSettings
) -> TaskResult:
    parent = event.data.parent
    page_id = event.data.page_id or (parent.id if parent and parent.type == "page" else None)
    if not page_id:
        return TaskResult("ignored", "comment not on a page")
    thread_id = notion_page_thread_id(page_id)
    metadata = await common.get_thread_metadata_safe(thread_id)
    if metadata is None:
        return TaskResult("ignored", "no thread for page")
    comment = next(
        (
            item
            for item in await client.list_comments(page_id)
            if normalize_notion_id(item.id) == normalize_notion_id(event.entity.id)
        ),
        None,
    )
    if comment is None or comment.created_by is None:
        return TaskResult("ignored", "comment not found")
    author = await _person(client, comment.created_by.id)
    if author is None or author.is_bot:
        return TaskResult("ignored", "comment author unknown or a bot")
    text = _comment_text(comment)
    if not text:
        return TaskResult("ignored", "empty comment")
    repo = metadata.get("repo")
    if not isinstance(repo, dict) or not repo.get("owner") or not repo.get("name"):
        return TaskResult("ignored", "thread has no repository")

    page = await client.get_page(page_id)
    requester = await _requester(client, comment.created_by.id)
    configurable, _ = await _configurable(
        thread_id,
        _page_ref(page, requester),
        {"owner": str(repo["owner"]), "name": str(repo["name"])},
        requester,
    )
    person = _person_identity(author)
    messages: list[RunMessage] = [
        person_introduction(person),
        human_input(
            text,
            {
                "sender_id": person["id"],
                "surface": "notion",
                "kind": "human",
                "data": {"comment_id": comment.id},
            },
        ),
    ]
    await _dispatch(thread_id, configurable, messages)
    return TaskResult("followed_up", "comment forwarded")


async def handle_notion_event(event: WebhookEvent) -> None:
    """Background entry point for one verified Notion webhook event."""
    settings = notion_settings()
    try:
        async with notion_client() as client:
            if event.type == "comment.created":
                await _handle_comment(client, event, settings)
                return
            page = await client.get_page(event.entity.id)
            if page.in_trash:
                return
            if settings.is_task_data_source(page.parent.data_source_id):
                await _handle_task_page(client, event, page, settings)
            elif settings.is_documents_data_source(page.parent.data_source_id):
                await _handle_design_page(client, event, page, settings)
    except NOTION_ERRORS:
        logger.exception(
            "Failed to handle Notion webhook event",
            extra={"notion_event_id": event.id, "notion_event_type": event.type},
        )
