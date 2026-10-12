"""Add nullable technical metadata for physical provider attempts."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('prompt_version', 'schema_version', 'policy_version'):
        op.add_column('provider_calls', sa.Column(name, sa.String(120), nullable=True))
    for name in ('semantic_attempt', 'transport_attempt', 'latency_ms'):
        op.add_column('provider_calls', sa.Column(name, sa.Integer(), nullable=True))
    op.create_check_constraint('ck_provider_calls_attempt_metadata', 'provider_calls',
        'semantic_attempt >= 1 AND transport_attempt >= 1 AND latency_ms >= 0')


def downgrade():
    op.drop_constraint('ck_provider_calls_attempt_metadata', 'provider_calls', type_='check')
    for name in ('latency_ms', 'transport_attempt', 'semantic_attempt', 'policy_version', 'schema_version', 'prompt_version'):
        op.drop_column('provider_calls', name)
