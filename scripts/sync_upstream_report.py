"""Writes the upstream sync PR's body: conflicts, and what the merge needs done outside the repo.

Upstream's changes to deployment, webhooks, sign-in and environment variables merge
cleanly yet break the fork's deployment until someone acts on them, so each area the
upstream range touches becomes a checkbox that sync_upstream_checklist.yml holds the
PR on until it is ticked.
"""

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

UPSTREAM_REPO = "langchain-ai/open-swe"
PROTECTED_FILES = Path(".github/fork-protected-files")
ENV_DECLARATIONS = "openswe/config.py"
ENV_VAR = re.compile(r'ENV\.var\(\s*"([A-Z0-9_]+)"')
BREAKING = re.compile(r"^\w+(\([^)]*\))?!:|BREAKING[ -]CHANGE", re.MULTILINE)
MARKER = re.compile(r"<!-- sync-upstream-report upstream=([0-9a-f]{40}) -->")
TICKED = re.compile(r"^- \[[xX]\] \*\*([^*]+)\*\*", re.MULTILINE)


@dataclass(frozen=True)
class ImpactArea:
    title: str
    action: str
    patterns: tuple[str, ...]

    def touched(self, files: list[str]) -> list[str]:
        return [f for f in files if any(fnmatch.fnmatch(f, p) for p in self.patterns)]


AREAS = (
    ImpactArea(
        "CI and deploy workflows",
        "Upstream's deploy workflows skip themselves in this fork. "
        "Mirror what changed into the fork's `*_aeteq.yml` workflows and their secrets.",
        (".github/workflows/*", "scripts/deploy_*", "scripts/build_preview_branch.py"),
    ),
    ImpactArea(
        "openswe-server build",
        "Check the LangSmith `openswe-server` deployment still builds and starts: "
        "Python version, graphs, auth handler and Dockerfile lines.",
        ("langgraph.json", "Dockerfile", "pyproject.toml"),
    ),
    ImpactArea(
        "MDA deployment and channels",
        "The channels declare the GitHub App's permissions, events and webhook. "
        "Check `open-swe-mda` deploys and the App's webhook URL, permissions and events "
        "match what upstream now expects.",
        (
            "mda/agent.py",
            "mda/identity.py",
            "mda/channels/*",
            "mda/pyproject.toml",
            "mda/CONNECTIONS.md",
            "vendor/managed-deepagents-sdk/crates/mda/src/deploy/*",
        ),
    ),
    ImpactArea(
        "Webhooks",
        "Check where GitHub, Slack and Notion deliver webhooks, the events they subscribe to "
        "and their signing secrets.",
        (
            "openswe/webhooks/*",
            "openswe/*/webhook.py",
            "openswe/*/webhooks.py",
            "ui/src/lib/slack-manifest.ts",
        ),
    ),
    ImpactArea(
        "Sign-in and auth",
        "Check dashboard sign-in, OAuth callback URLs and the Agent Server auth handler "
        "still work for this deployment.",
        (
            "openswe/api/agent_server_auth.py",
            "openswe/dashboard/auth_routes.py",
            "openswe/dashboard/*login*.py",
            "openswe/dashboard/*oauth*.py",
            "openswe/dashboard/principal.py",
            "ui/src/routes/login.tsx",
        ),
    ),
    ImpactArea(
        "Database migrations",
        "Migrations run when `openswe-server` deploys. "
        "Check for long locks, destructive changes or backfills.",
        ("openswe/database/migrations/versions/*",),
    ),
    ImpactArea(
        "Setup docs",
        "Upstream documents manual setup steps here. Read the diff for anything to do by hand.",
        ("docs/INSTALLATION.md", "docs/DEVELOPMENT.md", "docs/CUSTOMIZATION.md", "mda/README.md"),
    ),
)


class UpstreamRange:
    """The upstream commits the sync brings in: those on ``head`` since ``base``."""

    def __init__(self, base: str, head: str) -> None:
        self.base = self._git("rev-parse", base).strip()
        self.head = self._git("rev-parse", head).strip()

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout

    @property
    def compare_url(self) -> str:
        return f"https://github.com/{UPSTREAM_REPO}/compare/{self.base}...{self.head}"

    def changed_files(self) -> list[str]:
        return self._git("diff", "--name-only", self.base, self.head).split()

    def breaking_commits(self) -> list[str]:
        log = self._git("log", "--format=%H%x00%s%x00%b%x1e", f"{self.base}..{self.head}")
        found = []
        for entry in log.split("\x1e"):
            if not entry.strip():
                continue
            sha, subject, body = entry.strip().split("\x00", 2)
            if BREAKING.search(f"{subject}\n{body}"):
                found.append(f"{sha[:10]} {subject}")
        return found

    def env_vars(self, rev: str) -> set[str]:
        try:
            source = self._git("show", f"{rev}:{ENV_DECLARATIONS}")
        except subprocess.CalledProcessError:
            return set()
        return set(ENV_VAR.findall(source))


class SyncReport:
    def __init__(self, upstream: UpstreamRange, conflicts: list[str], reported: str) -> None:
        self.upstream = upstream
        self.conflicts = conflicts
        self.files = upstream.changed_files()
        # Ticks carry over only while upstream stays put: new upstream changes need a new look.
        marker = MARKER.search(reported)
        same_upstream = marker is not None and marker[1] == upstream.head
        self.ticked = set(TICKED.findall(reported)) if same_upstream else set()

    def _protected_area(self) -> ImpactArea:
        lines = PROTECTED_FILES.read_text().splitlines() if PROTECTED_FILES.exists() else []
        patterns = tuple(
            line.strip() for line in lines if line.strip() and not line.startswith("#")
        )
        return ImpactArea(
            "Fork-protected files",
            "These carry the fork's own behavior (`.github/fork-protected-files`). "
            "Even where they merged cleanly, check that behavior survived.",
            patterns,
        )

    def _item(self, area: ImpactArea, details: list[str]) -> list[str]:
        return [
            f"- [{'x' if area.title in self.ticked else ' '}] **{area.title}**: {area.action}",
            f"  <details><summary>{len(details)} changed</summary>",
            "",
            *(f"  - `{line}`" for line in details),
            "",
            "  </details>",
        ]

    def _env_item(self) -> list[str]:
        before = self.upstream.env_vars(self.upstream.base)
        after = self.upstream.env_vars(self.upstream.head)
        added, removed = sorted(after - before), sorted(before - after)
        if not added and not removed:
            return []
        area = ImpactArea(
            "Environment variables",
            f"Set new variables on `openswe-server` before merging (see `{ENV_DECLARATIONS}` "
            "for what each does); removed ones can be deleted once it deploys.",
            (),
        )
        return self._item(area, [f"+ {n}" for n in added] + [f"- {n}" for n in removed])

    def checklist(self) -> list[str]:
        items: list[str] = []
        for area in (*AREAS, self._protected_area()):
            if touched := area.touched(self.files):
                items += self._item(area, touched)
        items += self._env_item()
        if breaking := self.upstream.breaking_commits():
            area = ImpactArea(
                "Commits marked breaking", "Read each and act on what it asks of operators.", ()
            )
            items += self._item(area, breaking)
        return items

    def render(self) -> str:
        if self.conflicts:
            status = (
                "Upstream merge has **unresolved conflicts**: rerere had no recorded resolution "
                "for these.\n\n"
                + "\n".join(f"- `{f}`" for f in self.conflicts)
                + "\n\nResolve locally: `git fetch origin && git checkout sync-upstream && "
                "git merge upstream/main`, fix the conflicts, commit and push. "
                "rerere remembers the resolution for next time."
            )
        else:
            status = "Upstream merged cleanly (or rerere resolved the conflicts)."
        checklist = self.checklist()
        actions = (
            "Merging deploys to production. Do each of these, or confirm it needs nothing, "
            "and tick it; the checklist check holds the PR until all are ticked.\n\n"
            + "\n".join(checklist)
            if checklist
            else "Nothing in this range touches deployment, webhooks, sign-in or configuration."
        )
        return (
            f"{status}\n\n"
            "**⚠️ Do NOT squash and merge this PR**: use a regular merge commit so upstream "
            "history is preserved. Squashing breaks future syncs.\n\n"
            f"## Deployment impact\n\n{actions}\n\n"
            f"[Upstream changes in this sync]({self.upstream.compare_url})\n\n"
            f"<!-- sync-upstream-report upstream={self.upstream.head} -->\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Merge base of the fork and upstream.")
    parser.add_argument("--head", required=True, help="Upstream revision being merged.")
    parser.add_argument("--conflicts", default="", help="Newline-separated conflicted files.")
    parser.add_argument(
        "--reported",
        default="",
        help="The open sync PR's body, whose ticks are kept while it reports the same --head.",
    )
    args = parser.parse_args()
    upstream = UpstreamRange(args.base, args.head)
    sys.stdout.write(SyncReport(upstream, args.conflicts.split(), args.reported).render())
