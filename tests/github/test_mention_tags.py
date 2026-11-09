"""Mention-handle matching, which keeps parallel deployments from double-firing."""

import pytest

from openswe.github import comments as github_comments


@pytest.mark.parametrize(
    "body",
    [
        "@jarvis-aeteq please fix this",
        "@Jarvis-Aeteq: please fix this",
        "(@jarvis-aeteq)",
        "hey @jarvis-aeteq, take a look",
        "please ask\n@jarvis-aeteq to help",
        "@Jarvis-Aeteq ping",
        "@jarvis-aeteq: do the thing",
    ],
)
def test_matches_configured_handles(body: str) -> None:
    assert github_comments.mentions_open_swe(body)


@pytest.mark.parametrize(
    "body",
    [
        "@jarvis please fix this",
        "@Jarvis: please fix this",
        "@jarvis-preview please fix this",
        "@jarvis-aeteq-preview please fix this",
        "@jarvis-aeteqfoo",
        "me@jarvis.io",
        "me@jarvis-aeteq.io",
        "user.@jarvis-aeteq",
        "user-@jarvis-aeteq",
        "@@jarvis-aeteq",
        "no mention here",
        "",
        None,
    ],
)
def test_ignores_longer_handles_and_empty(body: str | None) -> None:
    assert not github_comments.mentions_open_swe(body)
