"""An in-memory Notion API shaped like the real Tasks / Document Hub workspace."""

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx2
from pydantic import JsonValue

from agent.notion.client import NotionClient
from agent.notion.settings import normalize_notion_id

JARVIS = "3e6d872b-594c-8176-bb78-000243d8cbe3"
INTEGRATION_BOT = "3e6c0b65-a473-8143-b8d4-0027ca778cb6"
ALICE = "2abd872b-594c-81d0-a736-0002165c1dba"
TASKS_DS = "3c3c0b65-a473-80ce-ac5f-000bcab990f9"
DOCS_DS = "3c3c0b65-a473-800f-8c5e-000b235e4641"
ASSIGNEE_ID = "%40JSP"
STATUS_ID = "AJ%3Fv"
DESIGN_STATUS_ID = "fef2b450-e417-4bb5-9e1b-7e76b47a2985"

type Json = dict[str, JsonValue]


def _people(ids: list[str]) -> list[JsonValue]:
    return [{"object": "user", "id": user_id} for user_id in ids]


def task_page(
    page_id: str,
    *,
    assignees: list[str] | None = None,
    status: str = "Not started",
    repo: str | None = "aeteq/sportsbook",
    designs: list[str] | None = None,
    number: int = 78,
    title: str = "Back office: show the app version",
    created_by: str = ALICE,
) -> Json:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://www.notion.so/{page_id.replace('-', '')}",
        "in_trash": False,
        "created_by": {"object": "user", "id": created_by},
        "parent": {"type": "data_source_id", "data_source_id": TASKS_DS},
        "properties": {
            "Task name": {
                "id": "title",
                "type": "title",
                "title": [{"type": "text", "plain_text": title}],
            },
            "ID": {
                "id": "lNza",
                "type": "unique_id",
                "unique_id": {"prefix": "DIG", "number": number},
            },
            "Assignee": {
                "id": ASSIGNEE_ID,
                "type": "people",
                "people": _people([JARVIS] if assignees is None else assignees),
            },
            "Status": {"id": STATUS_ID, "type": "status", "status": {"name": status}},
            "Repository": {
                "id": "CJ%40j",
                "type": "select",
                "select": {"name": repo} if repo else None,
            },
            "Pull Request URL": {"id": "Ae%5ET", "type": "url", "url": None},
            "Design": {
                "id": "%3CEwf",
                "type": "relation",
                "relation": [{"id": doc_id} for doc_id in designs or []],
            },
            "Due date": {"id": "k%3BOd", "type": "date", "date": {"start": "2026-10-01"}},
        },
    }


def design_page(page_id: str, *, status: str, title: str = "Tech Design: app version") -> Json:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://www.notion.so/{page_id.replace('-', '')}",
        "in_trash": False,
        "parent": {"type": "data_source_id", "data_source_id": DOCS_DS},
        "properties": {
            "Doc name": {
                "id": "title",
                "type": "title",
                "title": [{"type": "text", "plain_text": title}],
            },
            "Status": {"id": DESIGN_STATUS_ID, "type": "status", "status": {"name": status}},
        },
    }


TASK_STATUS_OPTIONS = ["Not started", "In progress", "In review", "Done"]


@dataclass
class FakeNotion:
    pages: dict[str, Json] = field(default_factory=dict)
    blocks: dict[str, list[Json]] = field(default_factory=dict)
    comments: dict[str, list[Json]] = field(default_factory=dict)
    users: dict[str, Json] = field(default_factory=dict)
    writes: list[tuple[str, str, Json]] = field(default_factory=list)
    fail_writes: bool = False

    def __post_init__(self) -> None:
        self.users.setdefault(
            ALICE,
            {
                "object": "user",
                "id": ALICE,
                "type": "person",
                "name": "Alice",
                "person": {"email": "alice@aeteq.com"},
            },
        )
        self.users.setdefault(
            INTEGRATION_BOT,
            {
                "object": "user",
                "id": INTEGRATION_BOT,
                "type": "bot",
                "name": "jarvis-openswe-agent",
            },
        )

    def add(self, page: Json) -> Json:
        self.pages[normalize_notion_id(str(page["id"]))] = page
        return page

    def page(self, page_id: str) -> Json:
        return self.pages[normalize_notion_id(page_id)]

    def comment_writes(self) -> list[str]:
        texts: list[str] = []
        for method, path, body in self.writes:
            if method == "POST" and path == "/v1/comments":
                rich_text = body["rich_text"]
                assert isinstance(rich_text, list)
                texts.append(
                    "".join(
                        str(item["text"]["content"])  # type: ignore[index]
                        for item in rich_text
                    )
                )
        return texts

    def property_writes(self) -> list[Json]:
        return [
            body["properties"]  # type: ignore[misc]
            for method, path, body in self.writes
            if method == "PATCH" and path.startswith("/v1/pages/")
        ]

    def _query(self, body: Json) -> list[JsonValue]:
        conditions = body["filter"]["and"]  # type: ignore[index]
        doc_id = normalize_notion_id(str(conditions[0]["relation"]["contains"]))  # type: ignore[index]
        results: list[JsonValue] = []
        for page in self.pages.values():
            if page["parent"]["data_source_id"] != TASKS_DS:  # type: ignore[index]
                continue
            relation = page["properties"]["Design"]["relation"]  # type: ignore[index]
            if any(normalize_notion_id(str(ref["id"])) == doc_id for ref in relation):  # type: ignore[union-attr]
                results.append(page)
        return results

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        method = request.method
        body: Json = json.loads(request.content) if request.content else {}
        if method in ("PATCH", "POST") and not path.endswith("/query"):
            self.writes.append((method, path, body))
            if self.fail_writes:
                return httpx2.Response(502, json={"code": "bad_gateway", "message": "down"})
        parts = path.removeprefix("/v1/").split("/")
        if parts[0] == "pages" and method == "GET":
            page = self.pages.get(normalize_notion_id(parts[1]))
            if page is None:
                return httpx2.Response(404, json={"code": "object_not_found", "message": "no"})
            return httpx2.Response(200, json=page)
        if parts[0] == "pages" and method == "PATCH":
            return httpx2.Response(200, json=self.pages[normalize_notion_id(parts[1])])
        if parts[0] == "data_sources" and len(parts) == 3:
            return httpx2.Response(200, json={"results": self._query(body), "has_more": False})
        if parts[0] == "data_sources":
            return httpx2.Response(
                200,
                json={
                    "id": parts[1],
                    "properties": {
                        "Status": {
                            "id": STATUS_ID,
                            "name": "Status",
                            "type": "status",
                            "status": {"options": [{"name": name} for name in TASK_STATUS_OPTIONS]},
                        }
                    },
                },
            )
        if parts[0] == "blocks":
            return httpx2.Response(
                200, json={"results": self.blocks.get(parts[1], []), "has_more": False}
            )
        if parts[0] == "comments" and method == "GET":
            block_id = parse_qs(request.url.query.decode())["block_id"][0]
            return httpx2.Response(
                200,
                json={
                    "results": self.comments.get(normalize_notion_id(block_id), []),
                    "has_more": False,
                },
            )
        if parts[0] == "comments" and method == "POST":
            return httpx2.Response(200, json={"id": "new-comment", "rich_text": []})
        if parts[0] == "users":
            user = self.users.get(parts[1])
            if user is None:
                return httpx2.Response(404, json={"code": "object_not_found", "message": "no"})
            return httpx2.Response(200, json=user)
        return httpx2.Response(404, json={"code": "not_found", "message": path})

    def client(self) -> NotionClient:
        return NotionClient(
            "secret", http=httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))
        )


def paragraph(text: str, *, block_id: str = "b", has_children: bool = False) -> Json:
    return {
        "object": "block",
        "id": block_id,
        "type": "paragraph",
        "has_children": has_children,
        "paragraph": {"rich_text": [{"type": "text", "plain_text": text}]},
    }


def comment(comment_id: str, text: str, *, author: str = ALICE) -> Json:
    return {
        "object": "comment",
        "id": comment_id,
        "discussion_id": "d1",
        "created_by": {"object": "user", "id": author},
        "created_time": "2026-09-25T10:00:00.000Z",
        "rich_text": [{"type": "text", "plain_text": text}],
    }
