import sys

import pytest

import agent.tools.comment_on_notion_task  # noqa: F401

tool = sys.modules["agent.tools.comment_on_notion_task"]


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    comments: list[tuple[str, str]] = []

    async def post(page_id: str, body: str) -> bool:
        comments.append((page_id, body))
        return True

    monkeypatch.setattr(tool, "post_notion_comment", post)
    return comments


def _config(monkeypatch: pytest.MonkeyPatch, configurable: dict[str, object]) -> None:
    monkeypatch.setattr("agent.run_config.get_config", lambda: {"configurable": configurable})


async def test_comments_on_the_task_that_started_the_run(
    monkeypatch: pytest.MonkeyPatch, posted: list[tuple[str, str]]
) -> None:
    _config(monkeypatch, {"source": "notion", "notion_page": {"id": "page-1"}})

    assert await tool.comment_on_notion_task("  Which footer?  ") == {"success": True}
    assert posted == [("page-1", "Which footer?")]


@pytest.mark.parametrize(
    ("configurable", "text"),
    [
        ({"source": "slack", "notion_page": {"id": "page-1"}}, "hi"),
        ({"source": "notion"}, "hi"),
        ({"source": "notion", "notion_page": {"id": "page-1"}}, "   "),
    ],
)
async def test_refuses_outside_a_notion_run_or_with_empty_text(
    monkeypatch: pytest.MonkeyPatch,
    posted: list[tuple[str, str]],
    configurable: dict[str, object],
    text: str,
) -> None:
    _config(monkeypatch, configurable)

    result = await tool.comment_on_notion_task(text)

    assert result["success"] is False
    assert posted == []
