from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, delete, update, text
from sqlalchemy.exc import SQLAlchemyError
from ..storage.database import unit_of_work
from ..storage.metrics import MetricJournal, WebsiteProviderAttempt
from .contracts import WebsiteBatch, AttemptBatch, IngestResult
from .repository import MetricRepository, fingerprint
from .limits import MetricsRateLimiter
from .errors import MetricsError


class MetricsCollector:
    def __init__(self, engine, settings, clock):
        self.engine, self.settings, self.clock = engine, settings, clock
        self.limiter = MetricsRateLimiter(engine, settings.metrics_environment, clock)

    def _lock_visitor(self, session, subject_id):
        # Serialize first-touch assignment and deletion without a new identity table.
        lock = int(fingerprint({'environment':self.settings.metrics_environment, 'visitor':str(subject_id)})[:16],16)
        session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':lock-(1 << 64) if lock >= (1 << 63) else lock})

    def ingest(self, batch: WebsiteBatch) -> IngestResult:
        batch = WebsiteBatch.model_validate(batch.model_dump())
        received = self.clock()
        accepted = 0
        try:
            with unit_of_work(self.engine) as session:
                for subject in sorted({event.subject_id for event in batch.events}, key=str):
                    self._lock_visitor(session, subject)
                repository = MetricRepository(session)
                for submitted in batch.events:
                    payload = submitted.model_dump(mode='json')
                    payload.pop('eventId')
                    event = submitted.model_copy(deep=True)
                    adjusted = batch.source == 'website_client' and abs(event.occurred_at-received) > timedelta(minutes=5)
                    if adjusted:
                        event.occurred_at = received
                    if event.name == 'page_viewed':
                        first = session.scalar(select(MetricJournal).where(
                            MetricJournal.subject_kind=='visitor', MetricJournal.subject_id==event.subject_id,
                            MetricJournal.environment==self.settings.metrics_environment,
                            MetricJournal.name=='page_viewed').order_by(MetricJournal.received_at, MetricJournal.event_id).limit(1))
                        campaign = event.properties.get('campaign')
                        event.properties['campaign'] = (first.properties['campaign'] if first else
                            'direct' if campaign is None else campaign if campaign in self.settings.metrics_campaign_codes else 'other')
                    accepted += repository.append(event, source=batch.source,
                        environment=self.settings.metrics_environment, received_at=received,
                        clock_adjusted=adjusted, submitted_hash=fingerprint(payload))
        except SQLAlchemyError:
            raise MetricsError('service_unavailable') from None
        return IngestResult(accepted=accepted, duplicates=len(batch.events)-accepted)

    def ingest_attempts(self, batch: AttemptBatch) -> IngestResult:
        batch = AttemptBatch.model_validate(batch.model_dump())
        try:
            with unit_of_work(self.engine) as session:
                for subject in sorted({attempt.subject_id for attempt in batch.attempts}, key=str):
                    self._lock_visitor(session, subject)
                accepted = sum(MetricRepository(session).settle_attempt(attempt,
                    environment=self.settings.metrics_environment) for attempt in batch.attempts)
        except SQLAlchemyError:
            raise MetricsError('service_unavailable') from None
        return IngestResult(accepted=accepted, duplicates=len(batch.attempts)-accepted)

    def delete_visitor(self, visitor_id) -> int:
        try:
            with unit_of_work(self.engine) as session:
                self._lock_visitor(session, visitor_id)
                deleted = session.execute(delete(MetricJournal).where(MetricJournal.subject_kind=='visitor',
                    MetricJournal.subject_id==visitor_id, MetricJournal.environment==self.settings.metrics_environment)).rowcount
                # Retain cost accounting while discarding the visitor association.
                session.execute(update(WebsiteProviderAttempt).where(WebsiteProviderAttempt.subject_id==visitor_id,
                    WebsiteProviderAttempt.environment==self.settings.metrics_environment).values(subject_id=uuid4()))
                return deleted
        except SQLAlchemyError:
            raise MetricsError('service_unavailable') from None
