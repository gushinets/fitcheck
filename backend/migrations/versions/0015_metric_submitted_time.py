"""Keep the original browser clock even when collector time is adjusted."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('metric_journal', sa.Column('submitted_occurred_at', sa.DateTime(timezone=True), nullable=True))
    # Previously adjusted timestamps are irrecoverable; never fabricate an original.
    op.execute("""UPDATE metric_journal SET submitted_occurred_at=occurred_at
        WHERE source='website_client' AND NOT clock_adjusted""")


def downgrade():
    op.drop_column('metric_journal', 'submitted_occurred_at')
