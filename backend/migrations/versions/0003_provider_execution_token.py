"""Attribute provider attempts to a leased worker execution."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('provider_calls', sa.Column('execution_token', sa.Uuid(), nullable=True))
    op.create_index('ix_provider_calls_execution', 'provider_calls', ['job_id', 'execution_token', 'state'])


def downgrade():
    op.drop_index('ix_provider_calls_execution', table_name='provider_calls')
    op.drop_column('provider_calls', 'execution_token')
