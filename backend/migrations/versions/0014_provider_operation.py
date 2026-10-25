"""Retain provider-call operation identity independently of technical jobs."""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('provider_calls', sa.Column('operation_id', sa.Uuid(), nullable=True))
    # Only the surviving same-owner FK is evidence. Never parse request keys or
    # use historical result proof to reconstruct already-erased relationships.
    op.execute("""UPDATE provider_calls AS calls SET operation_id=jobs.id
        FROM jobs WHERE calls.job_id=jobs.id AND calls.owner_id=jobs.owner_id""")
    op.create_check_constraint('ck_provider_calls_operation_owner', 'provider_calls',
        'owner_id IS NOT NULL OR operation_id IS NULL')
    op.create_check_constraint('ck_provider_calls_job_operation', 'provider_calls',
        'job_id IS NULL OR operation_id IS NULL OR operation_id=job_id')
    op.execute("""CREATE OR REPLACE FUNCTION fitcheck_anonymize_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE provider_calls SET owner_id=NULL, job_id=NULL, operation_id=NULL, request_key=NULL WHERE owner_id=OLD.id;
        RETURN OLD; END $$""")


def downgrade():
    op.execute("""CREATE OR REPLACE FUNCTION fitcheck_anonymize_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE provider_calls SET owner_id=NULL, job_id=NULL, request_key=NULL WHERE owner_id=OLD.id;
        RETURN OLD; END $$""")
    op.drop_constraint('ck_provider_calls_job_operation', 'provider_calls', type_='check')
    op.drop_constraint('ck_provider_calls_operation_owner', 'provider_calls', type_='check')
    op.drop_column('provider_calls', 'operation_id')
