"""Add optional versioned provider usage provenance, preserving legacy values."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('cached_input_tokens', 'cache_write_tokens', 'reasoning_tokens'):
        op.add_column('provider_calls', sa.Column(name,sa.Integer(),nullable=True))
    for name,size in (('cost_basis',20),('rate_version',120)):
        op.add_column('provider_calls',sa.Column(name,sa.String(size),nullable=True))
    # Nullable additions intentionally leave historical SDK costs untouched.
    for table in ('provider_calls','website_provider_attempts'):
        for name,size in (('cost_reason',80),('service_tier',40),('processing_region',40),('response_model',200)):
            op.add_column(table,sa.Column(name,sa.String(size),nullable=True))
        op.alter_column(table,'cost',type_=sa.Numeric(24,12),existing_type=sa.Numeric(20,8))
    op.create_check_constraint('ck_provider_calls_usage_details','provider_calls',
        'cached_input_tokens>=0 AND cache_write_tokens>=0 AND reasoning_tokens>=0 AND coalesce(cached_input_tokens,0)+coalesce(cache_write_tokens,0)<=input_tokens AND reasoning_tokens<=output_tokens')
    op.create_check_constraint('ck_provider_calls_cost_basis','provider_calls',
        "cost_basis IS NULL OR (cost_basis IN ('unknown','estimated','reported') AND (cost IS NULL)=(cost_basis='unknown'))")


def downgrade():
    op.drop_constraint('ck_provider_calls_cost_basis','provider_calls',type_='check')
    op.drop_constraint('ck_provider_calls_usage_details','provider_calls',type_='check')
    for table in ('provider_calls','website_provider_attempts'):
        # Refuse a lossy rollback rather than silently rounding post-upgrade data.
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE cost <> round(cost,8)) THEN RAISE EXCEPTION 'Cannot narrow cost precision without loss'; END IF; END $$")
        op.alter_column(table,'cost',type_=sa.Numeric(20,8),existing_type=sa.Numeric(24,12))
        for name in ('cost_reason','service_tier','processing_region','response_model'):
            op.drop_column(table,name)
    for name in ('cached_input_tokens','cache_write_tokens','reasoning_tokens','cost_basis','rate_version'):
        op.drop_column('provider_calls',name)
