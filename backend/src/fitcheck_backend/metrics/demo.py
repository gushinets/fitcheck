"""Server-verified guest observations, separate from account attribution."""
from sqlalchemy import select
from ..auth.errors import AuthError
from ..storage.guest_repository import require_identity
from ..storage.models import Owner, User, Job, AnalysisRecord
from ..storage.metrics import MetricDemoLink


def demo_link(session, event, identity, environment, now):
    if event.properties.get('flow') != 'demo' or identity is None or identity.mode != 'guest':
        return None
    # Same order as admission/claim/deletion: owner before session. Recheck the
    # session in this transaction so a stale API resolution cannot grant proof.
    owner = session.scalar(select(Owner).where(Owner.id == identity.owner_id).with_for_update())
    if owner is None or owner.kind != 'guest':
        return None
    try:
        guest = require_identity(session, identity, now, allow_claim_receipt=True)
    except AuthError:
        return None
    current_owner = (session.scalar(select(User.owner_id).where(User.id == guest.claimed_by_user_id))
                     if guest.claimed_by_user_id else identity.owner_id)
    job_id = result_id = None
    request_id = event.properties.get('requestId')
    if event.name == 'analysis_result_viewed':
        result = session.scalar(select(AnalysisRecord).where(
            AnalysisRecord.id == event.properties['resultId'], AnalysisRecord.owner_id == current_owner))
        job = session.get(Job, event.operation_id) if event.operation_id else None
        if (result is None or job is None or result.job_id != job.id or job.owner_id != current_owner
                or job.type != 'analysis' or job.status != 'succeeded'
                or job.input.get('mode') != 'guest' or job.input.get('sessionId') != str(identity.session_id)):
            return None
        job_id, result_id = job.id, result.id
    elif event.name not in {'vacancy_input_started', 'extraction_requested', 'analysis_requested'}:
        return None
    # A request key is a correlation, never evidence of admission. A subsequent
    # domain job joins by this exact idempotency key and original guest session.
    first = result_id is not None and session.scalar(select(MetricDemoLink.event_id).where(
        MetricDemoLink.environment == environment, MetricDemoLink.visitor_id == event.subject_id,
        MetricDemoLink.result_id == result_id, MetricDemoLink.first_view).limit(1)) is None
    return MetricDemoLink(event_id=event.event_id, guest_owner_id=identity.owner_id,
        environment=environment, visitor_id=event.subject_id, request_id=request_id,
        job_id=job_id, result_id=result_id, first_view=first)
