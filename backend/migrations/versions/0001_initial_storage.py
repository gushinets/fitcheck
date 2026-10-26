"""Initial website-only FitCheck schema, immutable payloads and auth limits."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Frozen column lists are intentional: schema revisions never import runtime models.
PROTECTED = {
    "profile_revisions": ["id", "revision", "profile", "created_at"],
    "vacancies": ["id", "vacancy", "source_url", "created_at"],
    "jobs": ["id", "type", "input", "request_hash", "idempotency_key", "created_at"],
    "analyses": ["id", "vacancy_id", "snapshot", "analysis", "created_at"],
}


def upgrade():
    op.execute("""
CREATE TABLE owners (
	kind VARCHAR(10) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_owners PRIMARY KEY (id),
	CONSTRAINT uq_owners_id UNIQUE (id, kind),
	CONSTRAINT ck_owners_kind CHECK (kind IN ('user','guest'))
)
""")
    op.execute("""
CREATE TABLE users (
	owner_id UUID NOT NULL,
	owner_kind VARCHAR(10) NOT NULL,
	normalized_email VARCHAR(254) NOT NULL,
	password_hash VARCHAR(1024) NOT NULL,
	email_verified_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT fk_users_owner_id_owners FOREIGN KEY(owner_id, owner_kind) REFERENCES owners (id, kind) ON DELETE CASCADE,
	CONSTRAINT ck_users_kind CHECK (owner_kind = 'user'),
	CONSTRAINT ck_users_normalized_email CHECK (normalized_email = lower(btrim(normalized_email)) AND length(normalized_email) > 0),
	CONSTRAINT uq_users_owner_id UNIQUE (owner_id),
	CONSTRAINT uq_users_normalized_email UNIQUE (normalized_email)
)
""")
    op.execute("""
CREATE TABLE profile_revisions (
	revision INTEGER NOT NULL,
	profile JSONB NOT NULL,
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_profile_revisions PRIMARY KEY (id),
	CONSTRAINT uq_profile_revisions_owner_id UNIQUE (owner_id, revision),
	CONSTRAINT ck_profile_revisions_revision CHECK (revision >= 1),
	CONSTRAINT ck_profile_revisions_profile_object CHECK (jsonb_typeof(profile) = 'object'),
	CONSTRAINT fk_profile_revisions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE preferences (
	owner_id UUID NOT NULL,
	locale VARCHAR(2) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_preferences PRIMARY KEY (owner_id),
	CONSTRAINT ck_preferences_locale CHECK (locale IN ('ru','en')),
	CONSTRAINT fk_preferences_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE drafts (
	owner_id UUID NOT NULL,
	vacancy JSONB NOT NULL,
	locale VARCHAR(2) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_drafts PRIMARY KEY (owner_id),
	CONSTRAINT ck_drafts_locale CHECK (locale IN ('ru','en')),
	CONSTRAINT ck_drafts_vacancy_object CHECK (jsonb_typeof(vacancy) = 'object'),
	CONSTRAINT fk_drafts_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE vacancies (
	vacancy JSONB NOT NULL,
	source_url VARCHAR(2048),
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_vacancies PRIMARY KEY (id),
	CONSTRAINT uq_vacancies_id UNIQUE (id, owner_id),
	CONSTRAINT ck_vacancies_vacancy_object CHECK (jsonb_typeof(vacancy) = 'object'),
	CONSTRAINT fk_vacancies_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE jobs (
	type VARCHAR(30) NOT NULL,
	status VARCHAR(20) NOT NULL,
	input JSONB NOT NULL,
	idempotency_key VARCHAR(200) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	attempts INTEGER NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE NOT NULL,
	lease_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	error JSONB,
	output JSONB,
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_jobs PRIMARY KEY (id),
	CONSTRAINT uq_jobs_owner_id UNIQUE (owner_id, type, idempotency_key),
	CONSTRAINT uq_jobs_id_owner UNIQUE (id, owner_id),
	CONSTRAINT uq_jobs_id_owner_type UNIQUE (id, owner_id, type),
	CONSTRAINT ck_jobs_type CHECK (type IN ('analysis','skill_suggestions','import')),
	CONSTRAINT ck_jobs_status CHECK (status IN ('queued','running','succeeded','failed')),
	CONSTRAINT ck_jobs_input_object CHECK (jsonb_typeof(input) = 'object'),
	CONSTRAINT ck_jobs_idempotency CHECK (length(idempotency_key) BETWEEN 1 AND 200 AND request_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_jobs_attempts CHECK (attempts >= 0),
	CONSTRAINT ck_jobs_lease CHECK ((status='running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status!='running' AND lease_token IS NULL AND lease_expires_at IS NULL)),
	CONSTRAINT ck_jobs_finished CHECK ((status IN ('succeeded','failed')) = (finished_at IS NOT NULL)),
	CONSTRAINT ck_jobs_error CHECK ((status='failed' AND error IS NOT NULL AND jsonb_typeof(error)='object') OR (status!='failed' AND error IS NULL)),
	CONSTRAINT ck_jobs_output CHECK ((status='succeeded' AND type IN ('skill_suggestions','import') AND output IS NOT NULL AND jsonb_typeof(output)='object') OR (NOT(status='succeeded' AND type IN ('skill_suggestions','import')) AND output IS NULL)),
	CONSTRAINT ck_jobs_suggestion_output CHECK (status!='succeeded' OR type!='skill_suggestions' OR (output ? 'skills' AND jsonb_typeof(output->'skills')='array')),
	CONSTRAINT ck_jobs_import_output CHECK (status!='succeeded' OR type!='import' OR (output ? 'importedCount' AND jsonb_typeof(output->'importedCount')='number')),
	CONSTRAINT fk_jobs_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_jobs_schedule ON jobs (status, available_at)
""")
    op.execute("""
CREATE INDEX ix_jobs_lease ON jobs (status, lease_expires_at)
""")
    op.execute("""
CREATE TABLE quota_buckets (
	policy_key VARCHAR(120) NOT NULL,
	window_start TIMESTAMP WITH TIME ZONE NOT NULL,
	resets_at TIMESTAMP WITH TIME ZONE,
	"limit" INTEGER NOT NULL,
	reserved INTEGER NOT NULL,
	consumed INTEGER NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_quota_buckets PRIMARY KEY (id),
	CONSTRAINT uq_quota_buckets_id UNIQUE (id, owner_id),
	CONSTRAINT uq_quota_buckets_owner_id UNIQUE (owner_id, policy_key, window_start),
	CONSTRAINT ck_quota_buckets_capacity CHECK ("limit" >= 0 AND reserved >= 0 AND consumed >= 0 AND reserved+consumed <= "limit"),
	CONSTRAINT fk_quota_buckets_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE guests (
	owner_id UUID NOT NULL,
	owner_kind VARCHAR(10) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	claimed_by_user_id UUID,
	claimed_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_guests PRIMARY KEY (id),
	CONSTRAINT fk_guests_owner_id_owners FOREIGN KEY(owner_id, owner_kind) REFERENCES owners (id, kind) ON DELETE CASCADE,
	CONSTRAINT ck_guests_kind CHECK (owner_kind = 'guest'),
	CONSTRAINT ck_guests_claim_pair CHECK ((claimed_by_user_id IS NULL) = (claimed_at IS NULL)),
	CONSTRAINT uq_guests_owner_id UNIQUE (owner_id),
	CONSTRAINT fk_guests_claimed_by_user_id_users FOREIGN KEY(claimed_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_guests_expiry ON guests (expires_at)
""")
    op.execute("""
CREATE TABLE auth_sessions (
	user_id UUID NOT NULL,
	kind VARCHAR(10) NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	csrf_digest VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_auth_sessions PRIMARY KEY (id),
	CONSTRAINT ck_auth_sessions_kind CHECK (kind = 'web'),
	CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT uq_auth_sessions_token_digest UNIQUE (token_digest)
)
""")
    op.execute("""
CREATE INDEX ix_auth_sessions_expiry ON auth_sessions (expires_at)
""")
    op.execute("""
CREATE TABLE auth_tokens (
	user_id UUID NOT NULL,
	purpose VARCHAR(30) NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	consumed_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_auth_tokens PRIMARY KEY (id),
	CONSTRAINT ck_auth_tokens_purpose CHECK (purpose IN ('verify_email','reset_password')),
	CONSTRAINT fk_auth_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT uq_auth_tokens_token_digest UNIQUE (token_digest)
)
""")
    op.execute("""
CREATE INDEX ix_auth_tokens_expiry ON auth_tokens (expires_at)
""")
    op.execute("""
CREATE TABLE profiles (
	owner_id UUID NOT NULL,
	current_revision INTEGER NOT NULL,
	CONSTRAINT pk_profiles PRIMARY KEY (owner_id),
	CONSTRAINT ck_profiles_revision CHECK (current_revision >= 1),
	CONSTRAINT fk_profiles_owner_id_profile_revisions FOREIGN KEY(owner_id, current_revision) REFERENCES profile_revisions (owner_id, revision) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_profiles_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE analyses (
	job_id UUID,
	job_type VARCHAR(30),
	vacancy_id UUID NOT NULL,
	profile_revision INTEGER,
	snapshot JSONB NOT NULL,
	analysis JSONB NOT NULL,
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_analyses PRIMARY KEY (id),
	CONSTRAINT uq_analyses_id UNIQUE (id, owner_id),
	CONSTRAINT fk_analyses_job_id_jobs FOREIGN KEY(job_id, owner_id, job_type) REFERENCES jobs (id, owner_id, type) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT fk_analyses_vacancy_id_vacancies FOREIGN KEY(vacancy_id, owner_id) REFERENCES vacancies (id, owner_id) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT fk_analyses_owner_id_profile_revisions FOREIGN KEY(owner_id, profile_revision) REFERENCES profile_revisions (owner_id, revision) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_analyses_job_pair CHECK ((job_id IS NULL AND job_type IS NULL) OR (job_id IS NOT NULL AND job_type IS NOT NULL AND job_type='analysis')),
	CONSTRAINT ck_analyses_payload_objects CHECK (jsonb_typeof(snapshot)='object' AND jsonb_typeof(analysis)='object'),
	CONSTRAINT uq_analyses_job_id UNIQUE (job_id),
	CONSTRAINT fk_analyses_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_analyses_history ON analyses (owner_id, created_at DESC, id DESC)
""")
    op.execute("""
CREATE TABLE quota_reservations (
	job_id UUID NOT NULL,
	bucket_id UUID NOT NULL,
	units INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_quota_reservations PRIMARY KEY (id),
	CONSTRAINT uq_quota_reservations_job_id UNIQUE (job_id, bucket_id),
	CONSTRAINT fk_quota_reservations_job_id_jobs FOREIGN KEY(job_id, owner_id) REFERENCES jobs (id, owner_id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT fk_quota_reservations_bucket_id_quota_buckets FOREIGN KEY(bucket_id, owner_id) REFERENCES quota_buckets (id, owner_id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_quota_reservations_state CHECK (units > 0 AND status IN ('reserved','consumed','released')),
	CONSTRAINT fk_quota_reservations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE provider_calls (
	owner_id UUID,
	job_id UUID,
	request_key VARCHAR(200),
	provider VARCHAR(120) NOT NULL,
	operation VARCHAR(120) NOT NULL,
	model VARCHAR(200) NOT NULL,
	attempt INTEGER NOT NULL,
	state VARCHAR(20) NOT NULL,
	input_tokens INTEGER,
	output_tokens INTEGER,
	cost NUMERIC(20, 8),
	currency VARCHAR(3),
	error_code VARCHAR(120),
	finished_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_provider_calls PRIMARY KEY (id),
	CONSTRAINT fk_provider_calls_job_id_jobs FOREIGN KEY(job_id, owner_id) REFERENCES jobs (id, owner_id) DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_provider_calls_job_owner CHECK (job_id IS NULL OR owner_id IS NOT NULL),
	CONSTRAINT ck_provider_calls_anonymous CHECK (owner_id IS NOT NULL OR (job_id IS NULL AND request_key IS NULL)),
	CONSTRAINT ck_provider_calls_state CHECK (attempt >= 1 AND state IN ('started','succeeded','failed','unknown')),
	CONSTRAINT ck_provider_calls_usage CHECK (input_tokens >= 0 AND output_tokens >= 0 AND cost >= 0),
	CONSTRAINT ck_provider_calls_currency CHECK ((cost IS NULL) = (currency IS NULL) AND (currency IS NULL OR currency IN ('USD','EUR','RUB'))),
	CONSTRAINT fk_provider_calls_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE SET NULL,
	CONSTRAINT uq_provider_calls_request_key UNIQUE (request_key)
)
""")
    op.execute("""
CREATE INDEX ix_provider_calls_owner_job ON provider_calls (owner_id, job_id, created_at)
""")
    op.execute("""
CREATE TABLE analysis_annotations (
	analysis_id UUID NOT NULL,
	corrected_score INTEGER,
	note VARCHAR(500),
	feedback_created_at TIMESTAMP WITH TIME ZONE,
	application_status VARCHAR(20) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	owner_id UUID NOT NULL,
	CONSTRAINT pk_analysis_annotations PRIMARY KEY (analysis_id),
	CONSTRAINT fk_analysis_annotations_analysis_id_analyses FOREIGN KEY(analysis_id, owner_id) REFERENCES analyses (id, owner_id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_analysis_annotations_score CHECK (corrected_score BETWEEN 0 AND 100),
	CONSTRAINT ck_analysis_annotations_feedback CHECK ((corrected_score IS NULL AND note IS NULL AND feedback_created_at IS NULL) OR (corrected_score IS NOT NULL AND feedback_created_at IS NOT NULL)),
	CONSTRAINT ck_analysis_annotations_status CHECK (application_status IN ('not_applied','applied','replied','interview','rejected','hired')),
	CONSTRAINT fk_analysis_annotations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_annotations_status ON analysis_annotations (owner_id, application_status)
""")
    op.execute("""
CREATE TABLE import_entries (
	source VARCHAR(20) NOT NULL,
	external_id VARCHAR(200) NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	analysis_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	CONSTRAINT pk_import_entries PRIMARY KEY (id),
	CONSTRAINT uq_import_entries_owner_id UNIQUE (owner_id, source, external_id),
	CONSTRAINT fk_import_entries_analysis_id_analyses FOREIGN KEY(analysis_id, owner_id) REFERENCES analyses (id, owner_id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
	CONSTRAINT ck_import_entries_source_hash CHECK (source='local_v1' AND content_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_import_entries_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE
)
""")

    op.execute("""CREATE TABLE auth_rate_buckets (
        scope VARCHAR(64) NOT NULL, subject_digest VARCHAR(64) NOT NULL,
        window_start TIMESTAMPTZ NOT NULL, attempts BIGINT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT pk_auth_rate_buckets PRIMARY KEY (scope,subject_digest,window_start),
        CONSTRAINT ck_auth_rate_buckets_positive_attempts CHECK (attempts > 0),
        CONSTRAINT ck_auth_rate_buckets_expiry CHECK (expires_at > window_start))""")
    op.execute('CREATE INDEX ix_auth_rate_buckets_expiry ON auth_rate_buckets(expires_at)')

    for table, columns in PROTECTED.items():
        changed = " OR ".join(f"NEW.{name} IS DISTINCT FROM OLD.{name}" for name in columns)
        op.execute(f"""CREATE FUNCTION fitcheck_guard_{table}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF {changed} THEN RAISE EXCEPTION 'immutable FitCheck payload' USING ERRCODE='23514'; END IF;
            RETURN NEW; END $$""")
        op.execute(f"CREATE TRIGGER fitcheck_immutable_{table} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION fitcheck_guard_{table}()")
    op.execute("""CREATE FUNCTION fitcheck_anonymize_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE provider_calls SET owner_id=NULL, job_id=NULL, request_key=NULL WHERE owner_id=OLD.id;
        RETURN OLD; END $$""")
    op.execute("CREATE TRIGGER fitcheck_owner_ledger BEFORE DELETE ON owners FOR EACH ROW EXECUTE FUNCTION fitcheck_anonymize_ledger()")


def downgrade():
    op.execute("DROP TRIGGER fitcheck_owner_ledger ON owners")
    op.execute("DROP FUNCTION fitcheck_anonymize_ledger()")
    for table in reversed(PROTECTED):
        op.execute(f"DROP TRIGGER fitcheck_immutable_{table} ON {table}")
        op.execute(f"DROP FUNCTION fitcheck_guard_{table}()")
    op.execute('DROP TABLE auth_rate_buckets')
    op.execute('DROP TABLE import_entries CASCADE')
    op.execute('DROP TABLE analysis_annotations CASCADE')
    op.execute('DROP TABLE quota_reservations CASCADE')
    op.execute('DROP TABLE provider_calls CASCADE')
    op.execute('DROP TABLE profiles CASCADE')
    op.execute('DROP TABLE guests CASCADE')
    op.execute('DROP TABLE auth_tokens CASCADE')
    op.execute('DROP TABLE auth_sessions CASCADE')
    op.execute('DROP TABLE analyses CASCADE')
    op.execute('DROP TABLE vacancies CASCADE')
    op.execute('DROP TABLE users CASCADE')
    op.execute('DROP TABLE quota_buckets CASCADE')
    op.execute('DROP TABLE profile_revisions CASCADE')
    op.execute('DROP TABLE preferences CASCADE')
    op.execute('DROP TABLE jobs CASCADE')
    op.execute('DROP TABLE drafts CASCADE')
    op.execute('DROP TABLE owners CASCADE')
