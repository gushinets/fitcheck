"""Confirmed visitor/account transitions; frozen additive DDL."""
from alembic import op
revision="0011"
down_revision="0010"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("\nCREATE TABLE metric_identity_transitions (\n\tenvironment VARCHAR(20) NOT NULL, \n\tvisitor_id UUID NOT NULL, \n\taccount_owner_id UUID, \n\tguest_owner_id UUID, \n\tkind VARCHAR(12) NOT NULL, \n\tsource_id UUID, \n\tauth_session_id UUID, \n\tcookie_issued_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trequest_started_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tanonymous_from TIMESTAMP WITH TIME ZONE, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tended_at TIMESTAMP WITH TIME ZONE, \n\tend_basis VARCHAR(12), \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_metric_identity_transitions PRIMARY KEY (id), \n\tCONSTRAINT uq_metric_identity_transitions_environment UNIQUE (environment, kind, source_id), \n\tCONSTRAINT ck_metric_identity_transitions_environment CHECK (environment IN ('development','production','test')), \n\tCONSTRAINT ck_metric_identity_transitions_kind CHECK (kind IN ('registered','login','claim','erased')), \n\tCONSTRAINT ck_metric_identity_transitions_guest CHECK ((kind='claim')=(guest_owner_id IS NOT NULL)), \n\tCONSTRAINT ck_metric_identity_transitions_identity CHECK ((kind='erased' AND account_owner_id IS NULL AND source_id IS NULL AND auth_session_id IS NULL AND anonymous_from IS NULL) OR (kind!='erased' AND account_owner_id IS NOT NULL AND source_id IS NOT NULL AND auth_session_id IS NOT NULL)), \n\tCONSTRAINT ck_metric_identity_transitions_expiry CHECK ((kind='claim')=(expires_at IS NULL)), \n\tCONSTRAINT ck_metric_identity_transitions_end CHECK ((ended_at IS NULL)=(end_basis IS NULL) AND (end_basis IS NULL OR end_basis IN ('revoked','expired'))), \n\tCONSTRAINT ck_metric_identity_transitions_time CHECK (cookie_issued_at<=occurred_at AND request_started_at<=occurred_at), \n\tCONSTRAINT fk_metric_identity_transitions_account_owner_id_owners FOREIGN KEY(account_owner_id) REFERENCES owners (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_metric_identity_transitions_guest_owner_id_owners FOREIGN KEY(guest_owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)\n\n")
    op.execute('CREATE INDEX ix_metric_identity_retention ON metric_identity_transitions (occurred_at, id)')
    op.execute('CREATE INDEX ix_metric_identity_session ON metric_identity_transitions (auth_session_id)')
    op.execute('CREATE INDEX ix_metric_identity_visitor ON metric_identity_transitions (environment, visitor_id, occurred_at)')
    op.execute("\nCREATE TABLE metric_visitor_boundaries (\n\tenvironment VARCHAR(20) NOT NULL, \n\tvisitor_id UUID NOT NULL, \n\tanonymous_floor TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_metric_visitor_boundaries PRIMARY KEY (environment, visitor_id), \n\tCONSTRAINT ck_metric_visitor_boundaries_environment CHECK (environment IN ('development','production','test'))\n)\n\n")
    op.execute('CREATE INDEX ix_metric_visitor_boundary_retention ON metric_visitor_boundaries (anonymous_floor)')

def downgrade():
    op.drop_table("metric_visitor_boundaries")
    op.drop_table("metric_identity_transitions")
