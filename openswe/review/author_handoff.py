"""Handing a published review's findings back to the agent thread that opened the PR.

Robin's reviewer posts as the GitHub App, and the GitHub channel skips the App's own
reviews, so nothing else tells the opening agent about them.
"""

import logging
from typing import Final

from openswe.github.pull_request_status import PullRequestClient
from openswe.github.pull_requests import PullRequest
from openswe.input_messages import SystemIdentity
from openswe.prompts import escape_for_data_block, prompt
from openswe.review.findings import Finding, comment_ids_for_finding

logger = logging.getLogger(__name__)

# Each push re-runs the review, so findings would otherwise ping-pong forever.
MAX_ROUNDS: Final = 3
_DATA_TAGS: Final = ("untrusted-review-finding",)
_SENDER: Final[SystemIdentity] = {
    "id": "system:review-handoff",
    "display_name": "Robin review",
    "platform": "open-swe",
}


class AuthorHandoff:
    @classmethod
    async def send(
        cls, pull_request: PullRequest, *, review_url: str, findings: list[Finding]
    ) -> bool:
        """Wake the PR's opening agent to address ``findings``; whether it now has them.

        ``False`` when no agent can be woken or the round cap has passed, which is when a
        person should take over. The first review past the cap says so on the PR, once.
        """
        if not findings or not pull_request.author_wakeable:
            return False
        rounds = pull_request.review_rounds_with_findings
        try:
            if rounds > MAX_ROUNDS:
                if rounds == MAX_ROUNDS + 1:
                    async with PullRequestClient.as_app(
                        pull_request.owner, pull_request.repo, pull_request.number
                    ) as pull:
                        await pull.comment(
                            f"Robin handed its review findings back to the agent that opened "
                            f"this PR for {MAX_ROUNDS} rounds, so it has stopped doing that. "
                            "Please review the remaining findings, or mention the agent to "
                            "have it keep going."
                        )
                return False
            return await pull_request.wake_author(
                prompt(
                    "runs/reviewer-findings-handoff",
                    pr_url=pull_request.url,
                    review_url=review_url,
                    round=rounds,
                    max_rounds=MAX_ROUNDS,
                    findings=[cls.fields(pull_request.url, finding) for finding in findings],
                ),
                sender=_SENDER,
            )
        except Exception:
            logger.exception(
                "Failed to hand review findings to the PR's agent thread",
                extra={
                    "pr_repo_full_name": pull_request.repo_full_name,
                    "pr_number": pull_request.number,
                    "review_round": rounds,
                },
            )
            return False

    @staticmethod
    def fields(pr_url: str, finding: Finding) -> dict[str, str]:
        """What the prompt shows of ``finding``; its text is fenced, since the reviewer
        wrote it after reading what anyone can put in the PR."""
        start, end = finding.get("start_line"), finding.get("end_line")
        if start is not None and end is not None and start != end:
            lines = f"lines {start}-{end}"
        elif start is not None or end is not None:
            lines = f"line {end if end is not None else start}"
        else:
            lines = ""
        comment_ids = comment_ids_for_finding(finding)
        return {
            "severity": finding["severity"],
            "title": escape_for_data_block(" ".join(finding["title"].split()), _DATA_TAGS),
            "file": escape_for_data_block(" ".join(finding["file"].split()), _DATA_TAGS),
            "lines": lines,
            "description": escape_for_data_block(finding["description"], _DATA_TAGS),
            "suggestion": escape_for_data_block(finding.get("suggestion") or "", _DATA_TAGS),
            "comment_url": f"{pr_url}#discussion_r{comment_ids[0]}" if comment_ids else "",
        }
