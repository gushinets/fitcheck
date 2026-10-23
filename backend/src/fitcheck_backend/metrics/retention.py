"""Bounded telemetry-only retention. Provider accounting is never deleted here."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlalchemy import delete, select, func, text
from ..storage.database import unit_of_work
from ..storage.metrics import MetricJournal, MetricCollection, MetricErasedVisitor
from .contracts import utc


@dataclass(frozen=True)
class MaintenanceResult:
    processed: int = 0
    deleted: int = 0
    tombstones_deleted: int = 0
    identity_deleted: int = 0
    backfill_target_at: datetime | None = None
    backfill_complete_through: datetime | None = None
    backfill_complete: bool | None = None


def valid_limit(limit):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Maintenance limit must be between 1 and 1000')


def cleanup_metrics(engine, *, now, dry_run=True, limit=1000) -> MaintenanceResult:
    valid_limit(limit)
    now = utc(now)
    cutoff = now-timedelta(days=180)
    with unit_of_work(engine) as session:
        session.execute(text("SET LOCAL statement_timeout='5s'"))
        maintenance_guard(session)
        rows = session.execute(select(MetricJournal.event_id, MetricJournal.source, MetricJournal.environment)
            .where(MetricJournal.received_at < cutoff)
            .order_by(MetricJournal.received_at, MetricJournal.event_id).limit(limit).with_for_update(skip_locked=True)).all()
        tombstones = session.execute(select(MetricErasedVisitor.environment, MetricErasedVisitor.visitor_digest)
            .where(MetricErasedVisitor.erased_at < now-timedelta(days=181))
            .order_by(MetricErasedVisitor.erased_at, MetricErasedVisitor.environment, MetricErasedVisitor.visitor_digest)
            .limit(limit-len(rows)).with_for_update(skip_locked=True)).all()
        from ..storage.metric_identity import MetricIdentityTransition as Link, MetricVisitorBoundary as Boundary
        remaining=limit-len(rows)-len(tombstones)
        identities=list(session.scalars(select(Link.id).where(Link.occurred_at<cutoff)
            .order_by(Link.occurred_at,Link.id).limit(remaining).with_for_update(skip_locked=True)))
        remaining-=len(identities)
        boundaries=session.execute(select(Boundary.environment,Boundary.visitor_id)
            .where(Boundary.anonymous_floor<cutoff).order_by(Boundary.anonymous_floor,Boundary.environment,Boundary.visitor_id)
            .limit(remaining).with_for_update(skip_locked=True)).all()
        processed=len(rows)+len(tombstones)+len(identities)+len(boundaries)
        if dry_run:
            return MaintenanceResult(processed=processed)
        if rows:
            session.execute(delete(MetricJournal).where(MetricJournal.event_id.in_([row.event_id for row in rows])))
            # Advancing only affected sources is conservative. Browser occurred_at
            # may be older than receipt time; retained rows never prove continuity.
            for source, environment in sorted({(row.source,row.environment) for row in rows}):
                collection = session.get(MetricCollection, (source, environment), with_for_update=True)
                if collection is not None:
                    oldest = session.scalar(select(func.min(MetricJournal.occurred_at)).where(
                        MetricJournal.source==source, MetricJournal.environment==environment))
                    collection.retention_floor = max(collection.retention_floor or cutoff, cutoff, oldest or cutoff)
                    collection.available_from = max(collection.available_from, collection.retention_floor)
        for environment, digest in tombstones:
            session.execute(delete(MetricErasedVisitor).where(MetricErasedVisitor.environment==environment,
                MetricErasedVisitor.visitor_digest==digest))
        if identities:session.execute(delete(Link).where(Link.id.in_(identities)))
        for environment,visitor in boundaries:
            session.execute(delete(Boundary).where(Boundary.environment==environment,Boundary.visitor_id==visitor))
        return MaintenanceResult(processed=processed, deleted=len(rows), tombstones_deleted=len(tombstones),
            identity_deleted=len(identities)+len(boundaries))


def maintenance_guard(session):
    # Both maintenance paths take this before any journal/owner/collection locks.
    # Fail fast so a repeatable-read snapshot cannot wait behind another drain.
    if not session.scalar(text('SELECT pg_try_advisory_xact_lock(5064669371900342605)')):
        raise ValueError('Another metrics maintenance operation is running; retry later')
