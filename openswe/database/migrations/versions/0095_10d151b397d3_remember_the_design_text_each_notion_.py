"""Remember the design text each Notion review covered.

A design review's later rounds review only what changed since this text. Review
rounds are queued by Notion webhooks, so ``created_by`` and ``updated_by`` stay NULL.
"""

from alembic import op

revision = "10d151b397d3"
down_revision = ["fab009aeaf70", "5fa6cdee053a"]
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notion_reviewed_design (
            id uuid PRIMARY KEY,
            notion_page_id text NOT NULL,
            reviewed_markdown text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_by uuid REFERENCES users (id) ON DELETE SET NULL,
            updated_by uuid REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX notion_reviewed_design_notion_page_id "
        "ON notion_reviewed_design (notion_page_id)"
    )


def downgrade() -> None:
    raise NotImplementedError
