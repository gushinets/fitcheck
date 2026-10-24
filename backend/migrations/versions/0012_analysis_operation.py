"""Preserve successful analysis operation proof through job cleanup."""
from alembic import op
revision="0012"
down_revision="0011"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("\nCREATE TABLE analysis_operation_proofs (\n\tanalysis_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tjob_created_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tmode VARCHAR(10), \n\tCONSTRAINT pk_analysis_operation_proofs PRIMARY KEY (analysis_id), \n\tCONSTRAINT ck_analysis_operation_proofs_mode CHECK (mode IS NULL OR mode IN ('account','guest')), \n\tCONSTRAINT fk_analysis_operation_proofs_analysis_id_analyses FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE, \n\tCONSTRAINT uq_analysis_operation_proofs_job_id UNIQUE (job_id)\n)\n\n")
    op.execute('CREATE INDEX ix_analysis_operation_proofs_retention ON analysis_operation_proofs (finished_at, analysis_id)')
    op.execute("CREATE INDEX ix_metric_journal_result_reference ON metric_journal ((CAST(properties ->> 'resultId' AS VARCHAR)), received_at) WHERE source='website_client' AND name IN ('analysis_result_viewed','feedback_saved')")

def downgrade():
    op.drop_index("ix_metric_journal_result_reference",table_name="metric_journal")
    op.drop_table("analysis_operation_proofs")
