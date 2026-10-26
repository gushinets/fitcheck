"""Bounded confirmed identity projections; never rewrite journal populations."""
from bisect import bisect_left
from itertools import groupby
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import select
from ..storage.identity import AuthSession
from ..storage.metric_identity import MetricIdentityTransition as Link
from ..storage.metrics import MetricDemoLink, MetricJournal
from .repository import valid_environment

MAX_ROWS=100_000


def bounded(session,statement):
    rows=session.execute(statement.limit(MAX_ROWS+1)).all()
    if len(rows)>MAX_ROWS:
        raise ValueError('Identity projection exceeds safe row limit')
    return rows


@dataclass(frozen=True)
class IdentityWindow:
    account_owner_id: UUID | None
    start: datetime
    end: datetime | None
    reason: str


@dataclass(frozen=True)
class IdentitySnapshot:
    transitions: tuple
    windows: tuple[IdentityWindow,...]


@dataclass(frozen=True)
class Attribution:
    account_owner_id: UUID | None
    reason: str


def _switches(links):
    """Earliest later different-account operation with no request overlap.

    Offline range minimum keeps large bounded histories O(n log n), including
    shared timestamps and long sequences of same-account sessions.
    """
    starts=sorted({link.request_started_at for link in links})
    tree=[() for _ in range(len(starts)+1)]
    def merge(left,right):
        owners={}
        for at,owner in (*left,*right):
            owners[owner]=min(at,owners.get(owner,at))
        return tuple(sorted(((at,owner) for owner,at in owners.items()),key=lambda item:(item[0],str(item[1])))[:2])
    result={}
    ordered=sorted(links,key=lambda link:link.occurred_at,reverse=True)
    for at,group in groupby(ordered,key=lambda link:link.occurred_at):
        group=list(group)
        index=len(starts)-bisect_left(starts,at)
        best=()
        while index:
            best=merge(best,tree[index]);index-=index&-index
        for link in group:
            result[link.id]=next((time for time,owner in best if owner!=link.account_owner_id),None)
        # Same-time transitions are never considered a later account switch.
        for link in group:
            index=len(starts)-bisect_left(starts,link.request_started_at)
            while index<len(tree):
                tree[index]=merge(tree[index],((at,link.account_owner_id),))
                index+=index&-index
    return result


def identity_snapshot(session,environment,visitor_id,now):
    valid_environment(environment)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware UTC time required')
    rows=bounded(session,select(Link,AuthSession).outerjoin(AuthSession,AuthSession.id==Link.auth_session_id)
        .where(Link.environment==environment,Link.visitor_id==visitor_id,
               Link.occurred_at>=now-timedelta(days=180),Link.occurred_at<=now)
        .order_by(Link.occurred_at,Link.id))
    return project_identity(rows)


def project_identity(rows):
    """Pure temporal resolver shared by per-visitor and bulk report reads."""
    windows=[]
    switches=_switches([link for link,_ in rows if link.kind!='claim'])
    for link,auth in rows:
        if link.kind=='claim':continue
        end=(min(auth.expires_at,auth.revoked_at or auth.expires_at) if auth else link.ended_at)
        reason='confirmed' if end is not None else 'missing_session_evidence'
        if end is None:
            end=link.expires_at  # Missing evidence cannot outlive the recorded hard expiry.
        if link.kind=='erased':
            end=link.expires_at
            reason='erased_account'
        # A later non-overlapping successful auth is a browser account boundary,
        # even when the caller did not send its old account cookie for rotation.
        switch=switches.get(link.id)
        if switch is not None:
            end=min(end,switch) if end is not None else switch
        windows.append(IdentityWindow(link.account_owner_id,link.occurred_at,end,reason))
    return IdentitySnapshot(tuple(link for link,_ in rows if link.kind!='erased'),tuple(windows))


def account_at(snapshot,at):
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('Aware UTC time required')
    candidates=[w for w in snapshot.windows if w.start<=at and (w.end is None or at<w.end)]
    if any(w.reason=='erased_account' for w in candidates):
        return Attribution(None,'erased_account')
    if any(w.reason!='confirmed' for w in candidates):
        return Attribution(None,'missing_session_evidence')
    owners={w.account_owner_id for w in candidates}
    if len(owners)>1:return Attribution(None,'ambiguous_sessions')
    return Attribution(next(iter(owners)), 'confirmed') if owners else Attribution(None,'no_confirmed_interval')


def claim_demo_events(session,claim):
    if claim.kind!='claim':raise ValueError('Claim transition required')
    # Arrival time may follow claim; observation time and provenance stay intact.
    rows=bounded(session,select(MetricJournal).join(MetricDemoLink,MetricDemoLink.event_id==MetricJournal.event_id)
        .where(MetricDemoLink.environment==claim.environment,MetricDemoLink.visitor_id==claim.visitor_id,
               MetricDemoLink.guest_owner_id==claim.guest_owner_id,
               MetricJournal.occurred_at>=claim.cookie_issued_at,
               MetricJournal.occurred_at<=claim.occurred_at)
        .order_by(MetricJournal.occurred_at,MetricJournal.event_id))
    return [row[0] for row in rows]
