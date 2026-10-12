import os
import pytest
from alembic import command
from sqlalchemy import text
from fitcheck_backend.config import Settings
from fitcheck_backend.storage.migrate import run_migrations, migration_config, schema_head

pytestmark = pytest.mark.integration


def test_upgrade_0002_preserves_identity_and_consumes_unbound_codes(engine):
    settings = Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL'])
    with engine.begin() as c:
        command.downgrade(migration_config(c), '0002')
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO owners(id,kind,created_at) VALUES ('00000000-0000-0000-0000-000000000001','user',now())"))
            c.execute(text("INSERT INTO users(id,owner_id,owner_kind,normalized_email,password_hash,created_at,updated_at) VALUES ('00000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000001','user','a@example.com','original-hash',now(),now())"))
            c.execute(text("INSERT INTO auth_sessions(id,user_id,kind,token_digest,csrf_digest,expires_at,created_at) VALUES ('00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000002','web',:d,:d,now()+interval '7 days',now())"), {'d':'a'*64})
            for index,purpose in enumerate(['verify_email','reset_password','extension_code'], 4):
                c.execute(text("INSERT INTO auth_tokens(id,user_id,purpose,token_digest,expires_at,created_at,code_challenge,redirect_uri) VALUES (CAST(:id AS uuid),'00000000-0000-0000-0000-000000000002',:purpose,:digest,now()+interval '1 hour',now(),:challenge,:redirect)"), {'id':f'00000000-0000-0000-0000-{index:012d}','purpose':purpose,'digest':str(index)*64,'challenge':'c'*43 if purpose=='extension_code' else None,'redirect':'https://example.com' if purpose=='extension_code' else None})
        run_migrations(settings)
        with engine.connect() as c:
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0003' == schema_head()
            assert c.scalar(text('SELECT password_hash FROM users')) == 'original-hash'
            assert c.scalar(text('SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL')) == 1
            assert c.scalar(text("SELECT count(*) FROM auth_tokens WHERE purpose!='extension_code' AND consumed_at IS NULL")) == 2
            assert c.scalar(text("SELECT consumed_at IS NOT NULL FROM auth_tokens WHERE purpose='extension_code'"))
    finally:
        run_migrations(settings)
