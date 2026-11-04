"""Merge the fork's wake config merge point into upstream's MDA run tools head."""

revision = "a118e6e8e8c8"
down_revision = ("b3e1d7c94a20", "00ba3da33037")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise NotImplementedError
