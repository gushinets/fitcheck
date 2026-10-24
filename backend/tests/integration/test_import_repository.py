from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
import importlib
import pytest
from sqlalchemy import select,func
from analysis_fixtures import DATA
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner,User,Job,AnalysisRecord,ImportEntry,AnalysisAnnotation
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.jobs.types import JobLease
from fitcheck_backend.contracts.imports import LocalImportRequest,parse_import_row

pytestmark=pytest.mark.integration


def raw_row(**change):
    return dict(id='row',createdAt='2025-01-01T00:00:00Z',job=deepcopy(DATA['vacancy']),analysis=deepcopy(DATA['analysis']),profile=deepcopy(DATA['profile']))|change


def lease_for(engine,source='alice',owner=None,**request):
    with unit_of_work(engine) as s:
        if owner is None:
            o=Owner(kind='user');s.add(o);s.flush();owner=o.id
            s.add(User(owner_id=owner,normalized_email=f'{owner}@example.com',password_hash='unused',email_verified_at=utcnow()));s.flush()
        payload=dict(version=1,source='website_indexeddb_v1',sourceUserId=source,history=[raw_row()])|request
        j=Job(owner_id=owner,type='import',status='running',input=payload,idempotency_key=str(uuid4()),request_hash='a'*64,lease_token=uuid4(),lease_expires_at=utcnow()+timedelta(minutes=10))
        s.add(j);s.flush()
        return JobLease(j.id,owner,'import',j.lease_token,1,payload)


def repo(s):return importlib.import_module('fitcheck_backend.storage.import_repository').ImportRepository(s)


def test_atomic_import_receipt_replay_and_source_conflicts(engine):
    lease=lease_for(engine)
    row=parse_import_row(raw_row(feedback={'correctedScore':61,'createdAt':'2025-01-02T00:00:00Z'}))
    with unit_of_work(engine) as s:
        out=repo(s).apply_row(lease,0,row)
        assert out.outcome=='imported'
    with unit_of_work(engine) as s:
        a=s.scalar(select(AnalysisRecord));assert a.profile_revision is None and a.created_at.year==2025
        assert a.snapshot['profileRevision'] is None
        ann=s.scalar(select(AnalysisAnnotation));ann.note='server edit'
    replay=lease_for(engine,owner=lease.owner_id)
    with unit_of_work(engine) as s:assert repo(s).apply_row(replay,0,row).outcome=='skipped'
    changed=lease_for(engine,owner=lease.owner_id)
    with unit_of_work(engine) as s:assert repo(s).apply_row(changed,0,parse_import_row(raw_row())).outcome=='conflict'
    other=lease_for(engine,source='bob',owner=lease.owner_id)
    with unit_of_work(engine) as s:assert repo(s).apply_row(other,0,row).outcome=='imported'
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(AnalysisRecord))==2
        assert s.scalar(select(AnalysisAnnotation).where(AnalysisAnnotation.note=='server edit')) is not None


def test_rollback_and_profile_outcome_survive_retry(engine):
    lease=lease_for(engine,profile=DATA['profile'],locale='ru')
    request=LocalImportRequest.model_validate(lease.input)
    with pytest.raises(RuntimeError):
        with unit_of_work(engine) as s:
            repo(s).apply_row(lease,0,parse_import_row(raw_row()));raise RuntimeError('crash')
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(ImportEntry))==0
    with unit_of_work(engine) as s:
        assert repo(s).apply_profile(lease,request)=='imported'
        assert repo(s).apply_preferences(lease,request)=='imported'
    with unit_of_work(engine) as s:
        assert repo(s).apply_profile(lease,request)=='imported'
        assert repo(s).apply_preferences(lease,request)=='imported'
    another=lease_for(engine,owner=lease.owner_id,profile={**DATA['profile'],'preferredRate':999},locale='en')
    with unit_of_work(engine) as s:
        assert repo(s).apply_profile(another,LocalImportRequest.model_validate(another.input))=='conflict'
        assert repo(s).apply_preferences(another,LocalImportRequest.model_validate(another.input))=='conflict'


def test_0009_upgrade_preserves_old_receipt_and_schema(engine,storage_factory):
    from alembic import command
    from sqlalchemy import text
    from fitcheck_backend.storage.migrate import migration_config,run_migrations,check_schema
    from fitcheck_backend.config import Settings
    with engine.begin() as c:command.downgrade(migration_config(c),'0008')
    with unit_of_work(engine) as s:
        owner,_,_,_,analysis,_=storage_factory(s)
        s.execute(text("INSERT INTO import_entries(id,owner_id,source,external_id,content_hash,analysis_id,created_at) VALUES(:id,:owner,'local_v1','old',:hash,:analysis,now())"),dict(id=uuid4(),owner=owner.id,hash='a'*64,analysis=analysis.id))
        identifier=analysis.id
    settings=Settings(database_url=engine.url.render_as_string(hide_password=False))
    run_migrations(settings);check_schema(settings);run_migrations(settings)
    with engine.connect() as c:
        assert c.scalar(text('select version_num from alembic_version'))=='0012'
        assert c.scalar(text('select source_user_id from import_entries'))=='__pre_0009__'
    with unit_of_work(engine) as s:assert s.get(AnalysisRecord,identifier) is not None


def test_item_fences_do_not_reload_complete_import_input(engine):
    from sqlalchemy import event
    lease=lease_for(engine)
    statements=[]
    def observe(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    try:
        with unit_of_work(engine) as s:repo(s).apply_row(lease,0,parse_import_row(raw_row()))
    finally:event.remove(engine,'before_cursor_execute',observe)
    job_reads=[sql.lower().split('from jobs')[0] for sql in statements if 'from jobs' in sql.lower()]
    assert job_reads and all('jobs.input' not in sql for sql in job_reads)
