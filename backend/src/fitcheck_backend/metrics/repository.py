from hashlib import sha256
import json

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from ..storage.metrics import MetricJournal, WebsiteProviderAttempt, MetricCollection, MetricErasedVisitor
from ..storage.base import utcnow
from .contracts import MetricEvent, WebsiteAttempt, Environment, ERASED_VISITOR_ID
from .registry import validate_event
from .errors import MetricsError


def fingerprint(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def valid_environment(environment):
    if environment not in {'development', 'production', 'test'}:
        raise MetricsError('invalid_request')


def visitor_digest(environment, subject_id):
    return fingerprint({'environment':environment, 'visitor':str(subject_id)})


class MetricRepository:
    def __init__(self, session):
        self.session = session

    def visitor_erased(self, subject_id, environment):
        return self.session.get(MetricErasedVisitor, (environment, visitor_digest(environment, subject_id))) is not None

    def _collection(self, source, environment, received, occurred):
        stmt = insert(MetricCollection).values(source=source, environment=environment,
                                               started_at=received, available_from=occurred)
        self.session.execute(stmt.on_conflict_do_update(index_elements=['source', 'environment'],
            set_={'available_from':func.greatest(MetricCollection.retention_floor,
                func.least(MetricCollection.available_from, stmt.excluded.available_from))}))

    def append(self, event, *, source, environment, received_at, clock_adjusted=False, submitted_hash=None, submitted_occurred_at=None):
        event = MetricEvent.model_validate(event.model_dump())
        validate_event(event, source=source)
        valid_environment(environment)
        if event.subject_kind == 'visitor' and self.visitor_erased(event.subject_id, environment):
            return False
        payload = event.model_dump(mode='json')
        payload.pop('eventId')
        # Bridge normalization changes stored dimensions/time, not transport identity.
        digest = submitted_hash if submitted_hash is not None else fingerprint(payload)
        values = dict(event_id=event.event_id, name=event.name, schema_version=event.schema_version,
            source=source, environment=environment, occurred_at=event.occurred_at,
            submitted_occurred_at=(submitted_occurred_at if submitted_occurred_at is not None else
                event.occurred_at if source=='website_client' and not clock_adjusted else None),
            received_at=received_at, subject_kind=event.subject_kind, subject_id=event.subject_id,
            owner_id=event.subject_id if event.subject_kind=='account' else None,
            session_id=event.session_id, operation_id=event.operation_id, domain_key=event.domain_key,
            properties=event.properties, payload_hash=digest, clock_adjusted=clock_adjusted)
        inserted = self.session.scalar(insert(MetricJournal).values(**values).on_conflict_do_nothing().returning(MetricJournal.event_id))
        if inserted is None:
            existing = self.session.scalar(select(MetricJournal).where(MetricJournal.event_id==event.event_id))
            same_id = existing is not None
            if existing is None and event.domain_key:
                existing = self.session.scalar(select(MetricJournal).where(
                    MetricJournal.environment==environment, MetricJournal.subject_id==event.subject_id,
                    MetricJournal.domain_key==event.domain_key))
            if existing is None or existing.payload_hash != digest or existing.environment != environment or (
                    same_id and existing.source != source):
                raise MetricsError('conflict')
            return False
        self._collection(source, environment, received_at, event.occurred_at)
        return True

    def settle_attempt(self, attempt, *, environment):
        attempt = WebsiteAttempt.model_validate(attempt.model_dump())
        valid_environment(environment)
        values = attempt.model_dump(by_alias=False)
        values['environment'] = environment
        if self.visitor_erased(attempt.subject_id, environment):
            values['subject_id'] = ERASED_VISITOR_ID
        inserted = self.session.scalar(insert(WebsiteProviderAttempt).values(**values)
            .on_conflict_do_nothing().returning(WebsiteProviderAttempt.call_id))
        if inserted is not None:
            self._collection('website_server', environment, utcnow(), attempt.started_at)
            return True
        row = self.session.scalar(select(WebsiteProviderAttempt).where(
            WebsiteProviderAttempt.call_id==attempt.call_id).with_for_update())
        # Erasure removes only the visitor association. Stable call IDs still
        # settle/replay, but cannot restore it; every other field stays checked.
        if row.subject_id == ERASED_VISITOR_ID:
            values['subject_id'] = ERASED_VISITOR_ID
        immutable = ('operation_id', 'subject_id', 'environment', 'purpose', 'ordinal', 'provider',
                     'model', 'prompt_version', 'policy_version', 'started_at')
        if any(getattr(row, key) != values[key] for key in immutable):
            raise MetricsError('conflict')
        if attempt.state == 'started':
            return False
        if row.state != 'started':
            if any(getattr(row, key) != value for key, value in values.items()):
                raise MetricsError('conflict')
            return False
        for key, value in values.items():
            setattr(row, key, value)
        self.session.flush()
        return True
