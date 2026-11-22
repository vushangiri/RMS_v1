"""Fresh-install schema for consolidated counter accounting."""

from pathlib import Path

from alembic import op

revision = "ledger_01"
down_revision = None


def upgrade():
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade():
    raise RuntimeError("Restore the pre-upgrade backup to roll back.")
