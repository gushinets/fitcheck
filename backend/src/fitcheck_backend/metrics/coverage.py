"""Per-runtime interruption markers; never infer recovery from another writer."""
import logging
from uuid import uuid4
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from ..storage.database import unit_of_work
from ..storage.metric_collection_gap import MetricCollectionGap

logger = logging.getLogger('fitcheck.metrics')


class CollectionInterruption:
    def __init__(self, engine, settings, clock):
        self.engine, self.clock, self.gap_id = engine, clock, None
        # Without a configured scope no destination can be safely attributed.
        environment = settings.metrics_environment or settings.metrics_database_environment
        collecting = settings.metrics_enabled and settings.metrics_environment is not None
        if collecting or environment is None:
            return
        gap_id = uuid4()
        self.started_at = clock()
        try:
            with unit_of_work(engine) as session:
                session.add(MetricCollectionGap(id=gap_id, source='backend_server',
                    environment=environment, started_at=self.started_at))
            self.gap_id = gap_id
        except SQLAlchemyError:
            # No exception detail: SQL/settings may include private values.
            logger.error('metrics_coverage_marker_failed', extra={'event': 'metrics_coverage_marker_failed'})

    def close(self):
        if self.gap_id is None:
            return
        try:
            with unit_of_work(self.engine) as session:
                session.execute(update(MetricCollectionGap).where(MetricCollectionGap.id == self.gap_id,
                    MetricCollectionGap.ended_at.is_(None)).values(ended_at=max(self.started_at, self.clock())))
            self.gap_id = None
        except SQLAlchemyError:
            # An unclosed interval remains unknown; another runtime cannot heal it.
            logger.error('metrics_coverage_marker_failed', extra={'event': 'metrics_coverage_marker_failed'})
