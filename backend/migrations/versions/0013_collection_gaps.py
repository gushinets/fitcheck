"""Preserve known collection interruptions independently of events."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('metric_collection_gaps',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('source', sa.String(30), nullable=False),
        sa.Column('environment', sa.String(20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_metric_collection_gaps'),
        sa.CheckConstraint("environment IN ('development','production','test')", name='ck_metric_collection_gaps_environment'),
        sa.CheckConstraint("source IN ('website_client','website_server','backend_server','reconstructed_backend')", name='ck_metric_collection_gaps_source'),
        sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name='ck_metric_collection_gaps_interval'))
    op.create_index('ix_metric_collection_gaps_scope', 'metric_collection_gaps', ['environment', 'source', 'started_at'])
    op.create_index('ix_metric_collection_gaps_retention', 'metric_collection_gaps', ['ended_at', 'id'])


def downgrade():
    op.drop_table('metric_collection_gaps')
