"""Merge the fork's wake config merge point into upstream's async worker head."""

revision = "b3e1d7c94a20"
down_revision = ("fe95bd992a81", "a7c12a7f1462")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise NotImplementedError
