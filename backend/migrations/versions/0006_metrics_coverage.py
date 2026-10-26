"""Explicit reconstruction completeness and an independent retention floor."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('retention_floor', 'backfill_target_at', 'backfill_complete_through'):
        op.add_column('metric_collections', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    # Existing availability may already have been advanced by cleanup. Never
    # infer restored continuity, or backfill completion, from an old first row.
    op.execute('UPDATE metric_collections SET retention_floor=available_from')


def downgrade():
    for name in ('backfill_complete_through', 'backfill_target_at', 'retention_floor'):
        op.drop_column('metric_collections', name)
