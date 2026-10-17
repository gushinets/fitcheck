"""Add guest identity, product operation and durable spending reservations.

DDL frozen at creation; never imports current application metadata.
"""
from alembic import op

revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("CREATE TABLE guest_sessions (\n\ttoken_digest VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\towner_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_guest_sessions PRIMARY KEY (id), \n\tCONSTRAINT ck_guest_sessions_digest CHECK (token_digest ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT uq_guest_sessions_token_digest UNIQUE (token_digest), \n\tCONSTRAINT fk_guest_sessions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)")
    op.execute("CREATE TABLE guest_claim_receipts (\n\taccount_owner_id UUID NOT NULL, \n\tguest_owner_id UUID NOT NULL, \n\tidempotency_key VARCHAR(200) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tclaimed_count INTEGER NOT NULL, \n\tprofile_imported BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_guest_claim_receipts PRIMARY KEY (id), \n\tCONSTRAINT uq_guest_claim_receipts_account_owner_id UNIQUE (account_owner_id, idempotency_key), \n\tCONSTRAINT ck_guest_claim_receipts_count CHECK (claimed_count>=0), \n\tCONSTRAINT ck_guest_claim_receipts_key_hash CHECK (length(idempotency_key) BETWEEN 1 AND 200 AND request_hash ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT fk_guest_claim_receipts_account_owner_id_owners FOREIGN KEY(account_owner_id) REFERENCES owners (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_guest_claim_receipts_guest_owner_id_owners FOREIGN KEY(guest_owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)")
    op.execute("CREATE TABLE extraction_reservations (\n\tbucket_id UUID NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\towner_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_extraction_reservations PRIMARY KEY (id), \n\tCONSTRAINT fk_extraction_reservations_bucket_id_quota_buckets FOREIGN KEY(bucket_id, owner_id) REFERENCES quota_buckets (id, owner_id) ON DELETE CASCADE, \n\tCONSTRAINT ck_extraction_reservations_state CHECK (status IN ('reserved','consumed','released')), \n\tCONSTRAINT fk_extraction_reservations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)")
    op.execute("CREATE TABLE budget_windows (\n\towner_id UUID, \n\tscope VARCHAR(20) NOT NULL, \n\tscope_key VARCHAR(120) NOT NULL, \n\twindow_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlimit_calls INTEGER NOT NULL, \n\tlimit_tokens INTEGER NOT NULL, \n\tlimit_usd NUMERIC(24, 12) NOT NULL, \n\tcalls INTEGER NOT NULL, \n\texposure_tokens INTEGER NOT NULL, \n\texposure_usd NUMERIC(24, 12) NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_budget_windows PRIMARY KEY (id), \n\tCONSTRAINT uq_budget_windows_scope UNIQUE (scope, scope_key, window_start), \n\tCONSTRAINT ck_budget_windows_scope CHECK (scope IN ('deployment','owner','job')), \n\tCONSTRAINT ck_budget_windows_ownership CHECK ((scope='deployment')=(owner_id IS NULL)), \n\tCONSTRAINT ck_budget_windows_limits CHECK (limit_calls>0 AND limit_tokens>0 AND limit_usd>0), \n\tCONSTRAINT ck_budget_windows_capacity CHECK (calls BETWEEN 0 AND limit_calls AND exposure_tokens BETWEEN 0 AND limit_tokens AND exposure_usd BETWEEN 0 AND limit_usd), \n\tCONSTRAINT fk_budget_windows_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)")
    op.execute("CREATE TABLE call_reservations (\n\tprovider_call_id UUID NOT NULL, \n\twindow_id UUID NOT NULL, \n\tinput_tokens INTEGER NOT NULL, \n\toutput_tokens INTEGER NOT NULL, \n\tusd NUMERIC(24, 12) NOT NULL, \n\trate_version VARCHAR(120) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_call_reservations PRIMARY KEY (provider_call_id, window_id), \n\tCONSTRAINT ck_call_reservations_bounds CHECK (input_tokens>=0 AND output_tokens>=0 AND usd>=0), \n\tCONSTRAINT ck_call_reservations_state CHECK (status IN ('reserved','settled','unknown')), \n\tCONSTRAINT fk_call_reservations_provider_call_id_provider_calls FOREIGN KEY(provider_call_id) REFERENCES provider_calls (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_call_reservations_window_id_budget_windows FOREIGN KEY(window_id) REFERENCES budget_windows (id) ON DELETE CASCADE\n)")


def downgrade():
    op.drop_table('call_reservations')
    op.drop_table('budget_windows')
    op.drop_table('extraction_reservations')
    op.drop_table('guest_claim_receipts')
    op.drop_table('guest_sessions')
