"""Bounded retention. Owner locks serialize deletion with claim and admission."""
from datetime import timedelta
from sqlalchemy import delete, select, update, exists, func, text
from ..storage.database import unit_of_work
from ..storage.models import (Owner, Guest, Job, AuthSession, AuthToken,
    AnalysisRecord, ProviderCall, QuotaReservation, ExtractionReservation, CallReservation)
from ..metrics.retention import valid_limit, maintenance_guard


def cleanup(engine, *, now, execute=False, limit=100):
    valid_limit(limit)
    if now.tzinfo is None or now.utcoffset() is None: raise ValueError('Aware UTC time required')
    counts = {}
    with unit_of_work(engine) as session:
        session.execute(text("SET LOCAL statement_timeout='10s'"))
        session.execute(text("SET LOCAL lock_timeout='1s'"))
        maintenance_guard(session)
        active = exists().where(Job.owner_id==Owner.id,Job.status.in_(['queued','running']))
        quota = exists().where(QuotaReservation.owner_id==Owner.id,QuotaReservation.status=='reserved')
        extraction = exists().where(ExtractionReservation.owner_id==Owner.id,ExtractionReservation.status=='reserved')
        provider_active = exists().where(ProviderCall.owner_id==Owner.id,ProviderCall.state=='started')
        provider_reserved = select(ProviderCall.id).join(CallReservation,CallReservation.provider_call_id==ProviderCall.id).where(ProviderCall.owner_id==Owner.id,CallReservation.status=='reserved').exists()
        guests = session.scalars(select(Owner.id).join(Guest,Guest.owner_id==Owner.id).where(
            Guest.claimed_by_user_id.is_(None),Guest.expires_at<now-timedelta(days=30),~active,~quota,~extraction,~provider_active,~provider_reserved)
            .order_by(Owner.id).limit(limit).with_for_update(of=Owner,skip_locked=True)).all()
        counts['guests'] = len(guests)
        if execute and guests: session.execute(delete(Owner).where(Owner.id.in_(guests)))
        for name, model, end in [('sessions',AuthSession,func.coalesce(AuthSession.revoked_at,AuthSession.expires_at)),
                                 ('tokens',AuthToken,func.coalesce(AuthToken.consumed_at,AuthToken.expires_at))]:
            ids = session.scalars(select(model.id).where(end<now-timedelta(days=7)).order_by(model.id).limit(limit).with_for_update(skip_locked=True)).all()
            counts[name] = len(ids)
            if execute and ids: session.execute(delete(model).where(model.id.in_(ids)))
        reserved = exists().where(QuotaReservation.job_id==Job.id,QuotaReservation.status=='reserved')
        unsettled = exists().where(ProviderCall.job_id==Job.id,ProviderCall.state=='started')
        provider_reserved_job = select(ProviderCall.id).join(CallReservation,CallReservation.provider_call_id==ProviderCall.id).where(ProviderCall.job_id==Job.id,CallReservation.status=='reserved').exists()
        jobs = session.scalars(select(Job.id).where(Job.status.in_(['succeeded','failed']),
            Job.finished_at<now-timedelta(days=30),~reserved,~unsettled,~provider_reserved_job).order_by(Job.id).limit(limit).with_for_update(skip_locked=True)).all()
        counts['jobs'] = len(jobs)
        if execute and jobs:
            session.execute(update(AnalysisRecord).where(AnalysisRecord.job_id.in_(jobs)).values(job_id=None,job_type=None))
            session.execute(update(ProviderCall).where(ProviderCall.job_id.in_(jobs)).values(job_id=None))
            session.execute(delete(Job).where(Job.id.in_(jobs)))
        calls = session.scalars(select(ProviderCall.id).where(ProviderCall.owner_id.is_(None),
            ProviderCall.created_at<now-timedelta(days=90),ProviderCall.state!='started',
            ~exists().where(CallReservation.provider_call_id==ProviderCall.id,CallReservation.status=='reserved'))
            .order_by(ProviderCall.id).limit(limit).with_for_update(skip_locked=True)).all()
        counts['anonymous_provider_calls'] = len(calls)
        if execute and calls: session.execute(delete(ProviderCall).where(ProviderCall.id.in_(calls)))
        counts['executed'] = execute
    return counts
