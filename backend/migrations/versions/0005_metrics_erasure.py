"""Anonymous deletion facts and bounded visitor erasure protection."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_metric_journal_retention', 'metric_journal', ['received_at', 'event_id'])
    op.alter_column('metric_journal', 'subject_id', nullable=True)
    op.drop_constraint(op.f('ck_metric_journal_identity'), 'metric_journal', type_='check')
    op.drop_constraint(op.f('ck_metric_journal_owner'), 'metric_journal', type_='check')
    op.create_check_constraint(op.f('ck_metric_journal_identity'), 'metric_journal', "schema_version=1 AND subject_kind IN ('visitor','account','anonymous')")
    op.create_check_constraint(op.f('ck_metric_journal_owner'), 'metric_journal', "(subject_kind='account' AND subject_id IS NOT NULL AND owner_id IS NOT NULL AND owner_id=subject_id) OR (subject_kind='visitor' AND subject_id IS NOT NULL AND owner_id IS NULL) OR (subject_kind='anonymous' AND subject_id IS NULL AND owner_id IS NULL AND name='account_deleted' AND source='backend_server' AND session_id IS NULL AND operation_id IS NULL AND domain_key IS NULL AND properties='{}'::jsonb)")
    op.create_table('metric_erased_visitors',
        sa.Column('environment', sa.String(20), nullable=False),
        sa.Column('visitor_digest', sa.String(64), nullable=False),
        sa.Column('erased_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('environment', 'visitor_digest', name=op.f('pk_metric_erased_visitors')),
        sa.CheckConstraint("environment IN ('development','production','test')", name=op.f('ck_metric_erased_visitors_environment')),
        sa.CheckConstraint("visitor_digest ~ '^[0-9a-f]{64}$'", name=op.f('ck_metric_erased_visitors_digest')))
    op.create_index('ix_metric_erased_visitors_expiry', 'metric_erased_visitors', ['erased_at'])


def downgrade():
    op.drop_index('ix_metric_journal_retention', table_name='metric_journal')
    op.drop_table('metric_erased_visitors')
    # Anonymous aggregates have no representation in 0004.
    op.execute("DELETE FROM metric_journal WHERE subject_kind='anonymous'")
    op.drop_constraint(op.f('ck_metric_journal_owner'), 'metric_journal', type_='check')
    op.drop_constraint(op.f('ck_metric_journal_identity'), 'metric_journal', type_='check')
    op.create_check_constraint(op.f('ck_metric_journal_identity'), 'metric_journal', "schema_version=1 AND subject_kind IN ('visitor','account')")
    op.create_check_constraint(op.f('ck_metric_journal_owner'), 'metric_journal', "(subject_kind='account' AND owner_id IS NOT NULL AND owner_id=subject_id) OR (subject_kind='visitor' AND owner_id IS NULL)")
    op.alter_column('metric_journal', 'subject_id', nullable=False)
