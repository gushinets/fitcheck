from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
import pytest
from sqlalchemy import event, select, func, text
from fitcheck_backend.auth.access import AccountDeletionService
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import User, AuthSession
from fitcheck_backend.storage.ownership import delete_owner, transfer_guest_analyses

pytestmark=pytest.mark.integration


def test_delete_racing_login_and_guest_claim_fails_closed(auth_components,storage_factory,monkeypatch):
    a=auth_components
    issued=a.service.register('a@example.com','correct horse battery','192.0.2.1')
    with unit_of_work(a.engine) as s:
        guest_owner,*_=storage_factory(s,kind='guest')
        guest_id=guest_owner.id
    reached,release=Event(),Event()
    observed=[False]
    def pause(conn,cursor,sql,params,context,many):
        if 'SELECT guests.owner_id' in sql and not observed[0]:
            observed[0]=True;reached.set();assert release.wait(5)
    event.listen(a.engine,'after_cursor_execute',pause)
    service=AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(service.delete,issued.principal,'correct horse battery')
            try:
                assert reached.wait(5)
                with unit_of_work(a.engine) as s:transfer_guest_analyses(s,guest_id,issued.principal.owner_id)
            finally:release.set()
            result.result(10)
    finally:event.remove(a.engine,'after_cursor_execute',pause)
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(User))==0
        assert s.scalar(select(func.count()).select_from(AuthSession))==0


def test_resolve_during_deletion_returns_unauthenticated(auth_components):
    a=auth_components
    issued=a.service.register('a@example.com','correct horse battery','192.0.2.1')
    reached,release=Event(),Event()
    def pause(conn,cursor,sql,params,context,many):
        if 'FROM auth_sessions JOIN users' in sql:
            reached.set();assert release.wait(5)
    event.listen(a.engine,'after_cursor_execute',pause)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(a.service.resolve,issued.token,'web')
            try:
                assert reached.wait(5)
                with unit_of_work(a.engine) as s:delete_owner(s,issued.principal.owner_id)
            finally:release.set()
            with pytest.raises(AuthError) as exc:result.result(5)
            assert exc.value.code=='unauthenticated'
    finally:event.remove(a.engine,'after_cursor_execute',pause)


def test_login_verification_cannot_admit_session_after_delete(auth_components,monkeypatch):
    a=auth_components
    issued=a.service.register('a@example.com','correct horse battery','192.0.2.1')
    reached,release=Event(),Event()
    main=get_ident()
    original=a.passwords.verify
    def pause(encoded,password):
        result=original(encoded,password)
        if get_ident()!=main:
            reached.set();assert release.wait(5)
        return result
    monkeypatch.setattr(a.passwords,'verify',pause)
    service=AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(a.service.login,'a@example.com','correct horse battery','192.0.2.1')
        try:
            assert reached.wait(5)
            service.delete(issued.principal,'correct horse battery')
        finally:release.set()
        with pytest.raises(AuthError) as exc:result.result(5)
        assert exc.value.code=='invalid_credentials'


def test_deletion_exhausts_three_fk_retries_and_rolls_back(auth_components):
    a=auth_components
    issued=a.service.register('a@example.com','correct horse battery','192.0.2.1')
    target=issued.principal.owner_id
    attempts=[]
    def observe(conn,cursor,sql,params,context,many):
        if 'DELETE FROM owners' in sql and target in params.values():attempts.append(1)
    with a.engine.begin() as c:
        c.execute(text(f"CREATE FUNCTION fitcheck_test_delete_race() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.id = '{target}'::uuid THEN RAISE EXCEPTION 'ownership race' USING ERRCODE='23503', CONSTRAINT='fk_guests_claimed_by_user_id_users'; END IF; RETURN OLD; END $$"))
        c.execute(text('CREATE TRIGGER fitcheck_test_delete_race BEFORE DELETE ON owners FOR EACH ROW EXECUTE FUNCTION fitcheck_test_delete_race()'))
    event.listen(a.engine,'before_cursor_execute',observe)
    try:
        with pytest.raises(AuthError) as exc:AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock).delete(issued.principal,'correct horse battery')
        assert exc.value.code=='ownership_conflict' and len(attempts)==3
        assert a.service.resolve(issued.token,'web').user_id==issued.principal.user_id
    finally:
        event.remove(a.engine,'before_cursor_execute',observe)
        with a.engine.begin() as c:
            c.execute(text('DROP TRIGGER fitcheck_test_delete_race ON owners'))
            c.execute(text('DROP FUNCTION fitcheck_test_delete_race()'))
