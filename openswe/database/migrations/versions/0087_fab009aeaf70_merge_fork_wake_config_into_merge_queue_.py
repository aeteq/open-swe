"""Merge the fork's wake config merge point into upstream's merge queue fence head."""

revision = "fab009aeaf70"
down_revision = ("0497c835bcfc", "a118e6e8e8c8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise NotImplementedError
