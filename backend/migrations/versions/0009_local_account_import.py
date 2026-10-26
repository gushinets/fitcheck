"""Durable local import outcomes and source identity; frozen DDL."""
from alembic import op
revision='0009'
down_revision='0008'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TABLE import_entries ADD COLUMN source_user_id VARCHAR(200) NOT NULL DEFAULT '__pre_0009__'")
    op.execute("ALTER TABLE import_entries ALTER COLUMN source_user_id DROP DEFAULT")
    op.execute("ALTER TABLE import_entries DROP CONSTRAINT uq_import_entries_owner_id")
    op.execute("ALTER TABLE import_entries ADD CONSTRAINT uq_import_entries_owner_id UNIQUE(owner_id,source,source_user_id,external_id)")
    op.execute("\nCREATE TABLE import_items (\n\tjob_id UUID NOT NULL, \n\titem_index INTEGER NOT NULL, \n\toutcome JSONB NOT NULL, \n\towner_id UUID NOT NULL, \n\tCONSTRAINT pk_import_items PRIMARY KEY (job_id, item_index), \n\tCONSTRAINT fk_import_items_job_id_jobs FOREIGN KEY(job_id, owner_id) REFERENCES jobs (id, owner_id) ON DELETE CASCADE, \n\tCONSTRAINT ck_import_items_index CHECK (item_index BETWEEN -2 AND 999), \n\tCONSTRAINT ck_import_items_outcome CHECK (jsonb_typeof(outcome)='object'), \n\tCONSTRAINT fk_import_items_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE CASCADE\n)\n\n")

def downgrade():
    # Multiple sources may share IDs; restoring the old uniqueness loses data.
    # Refuse that incompatible downgrade instead of deleting user records.
    op.execute("ALTER TABLE import_entries DROP CONSTRAINT uq_import_entries_owner_id")
    op.execute("ALTER TABLE import_entries ADD CONSTRAINT uq_import_entries_owner_id UNIQUE(owner_id,source,external_id)")
    op.drop_table('import_items')
    op.drop_column('import_entries','source_user_id')
