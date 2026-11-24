"""The thread's sandbox as both sides ready it: where its checkouts live and who commits in them."""

import os
from typing import Final

from pydantic import BaseModel

# Repositories live in ``/workspace/<repo>``, where workspace images preload them.
WORK_DIR: Final = "/workspace"
# A deployment acting as its own GitHub App commits under that App's name and noreply address.
GIT_NAME: Final = os.environ.get("OPEN_SWE_GIT_NAME", "").strip() or "Robin"
# The open-swe user's noreply address: the bot's numeric noreply
# (215916821+open-swe[bot]@...) doesn't resolve to a GitHub account Vercel accepts,
# which broke preview deploys on commits carrying this co-author.
GIT_EMAIL: Final = (
    os.environ.get("OPEN_SWE_GIT_EMAIL", "").strip() or "open-swe@users.noreply.github.com"
)


class GitIdentity(BaseModel):
    """Who commits in the thread's sandbox: its owner, or the bot when it has none."""

    name: str = GIT_NAME
    email: str = GIT_EMAIL
