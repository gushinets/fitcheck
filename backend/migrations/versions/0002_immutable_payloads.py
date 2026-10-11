"""Protect immutable inputs and anonymize technical ledger on owner deletion."""
from alembic import op

revision = "0002"
down_revision = "0001"
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
