"""Store optional product variation labels alongside catalogue names."""

from alembic import op

revision = "ledger_02"
down_revision = "ledger_01"


def upgrade():
    op.execute("alter table item add column variation varchar(80) not null default ''")


def downgrade():
    raise RuntimeError("Restore the pre-upgrade backup to roll back.")
