"""Verified guest demo observations; frozen additive DDL."""
from alembic import op
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("\nCREATE TABLE metric_demo_links (\n\tevent_id UUID NOT NULL, \n\tguest_owner_id UUID NOT NULL, \n\tenvironment VARCHAR(20) NOT NULL, \n\tvisitor_id UUID NOT NULL, \n\trequest_id UUID, \n\tjob_id UUID, \n\tresult_id UUID, \n\tfirst_view BOOLEAN NOT NULL, \n\tCONSTRAINT pk_metric_demo_links PRIMARY KEY (event_id), \n\tCONSTRAINT ck_metric_demo_links_environment CHECK (environment IN ('development','production','test')), \n\tCONSTRAINT ck_metric_demo_links_result_job CHECK (result_id IS NULL OR job_id IS NOT NULL), \n\tCONSTRAINT ck_metric_demo_links_first_view CHECK (NOT first_view OR result_id IS NOT NULL), \n\tCONSTRAINT fk_metric_demo_links_event_id_metric_journal FOREIGN KEY(event_id) REFERENCES metric_journal (event_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_metric_demo_links_guest_owner_id_owners FOREIGN KEY(guest_owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)\n\n")
    op.execute('CREATE INDEX ix_metric_demo_request ON metric_demo_links (guest_owner_id, request_id)')
    op.execute('CREATE UNIQUE INDEX uq_metric_demo_first_view ON metric_demo_links (environment, visitor_id, result_id) WHERE first_view')

def downgrade():
    op.drop_table("metric_demo_links")
