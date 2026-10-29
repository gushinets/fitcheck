"""Allow an explicit unlimited operation quota while retaining usage accounting."""
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('quota_buckets', 'limit', nullable=True)
    op.alter_column('budget_windows', 'limit_usd', nullable=True)


def downgrade():
    op.alter_column('budget_windows', 'limit_usd', nullable=False)
    op.alter_column('quota_buckets', 'limit', nullable=False)
