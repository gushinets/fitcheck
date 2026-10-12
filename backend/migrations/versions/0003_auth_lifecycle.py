"""Bind extension codes to sessions and persist shared authentication limits."""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE auth_sessions ADD CONSTRAINT uq_auth_sessions_id UNIQUE (id,user_id)')
    op.execute('ALTER TABLE auth_tokens ADD COLUMN issued_session_id UUID')
    op.execute("UPDATE auth_tokens SET consumed_at=now() WHERE purpose='extension_code' AND consumed_at IS NULL")
    op.execute('ALTER TABLE auth_tokens ADD CONSTRAINT fk_auth_tokens_issued_session_id_auth_sessions FOREIGN KEY (issued_session_id,user_id) REFERENCES auth_sessions(id,user_id) ON DELETE CASCADE')
    op.execute("ALTER TABLE auth_tokens ADD CONSTRAINT ck_auth_tokens_session_binding CHECK ((purpose='extension_code' AND (issued_session_id IS NOT NULL OR consumed_at IS NOT NULL)) OR (purpose!='extension_code' AND issued_session_id IS NULL))")
    op.execute('''CREATE TABLE auth_rate_buckets (
        scope VARCHAR(64) NOT NULL, subject_digest VARCHAR(64) NOT NULL,
        window_start TIMESTAMPTZ NOT NULL, attempts BIGINT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT pk_auth_rate_buckets PRIMARY KEY (scope,subject_digest,window_start),
        CONSTRAINT ck_auth_rate_buckets_positive_attempts CHECK (attempts > 0),
        CONSTRAINT ck_auth_rate_buckets_expiry CHECK (expires_at > window_start))''')
    op.execute('CREATE INDEX ix_auth_rate_buckets_expiry ON auth_rate_buckets(expires_at)')


def downgrade():
    op.execute('DROP TABLE auth_rate_buckets')
    op.execute('ALTER TABLE auth_tokens DROP CONSTRAINT ck_auth_tokens_session_binding')
    op.execute('ALTER TABLE auth_tokens DROP CONSTRAINT fk_auth_tokens_issued_session_id_auth_sessions')
    op.execute('ALTER TABLE auth_tokens DROP COLUMN issued_session_id')
    op.execute('ALTER TABLE auth_sessions DROP CONSTRAINT uq_auth_sessions_id')
