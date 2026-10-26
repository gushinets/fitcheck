\set ON_ERROR_STOP on
DO $$
BEGIN
  IF (SELECT count(*) FROM alembic_version) <> 1 THEN
    RAISE EXCEPTION 'Migration revision missing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated) THEN
    RAISE EXCEPTION 'Restored constraints are not validated';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='owners'::regclass AND NOT tgisinternal) THEN
    RAISE EXCEPTION 'Owner deletion trigger missing';
  END IF;
END $$;
SELECT count(*) FROM owners;
SELECT count(*) FROM users;
SELECT count(*) FROM jobs;
SELECT count(*) FROM analyses;
SELECT count(*) FROM provider_calls;
