"""Operator-only report builder; all reads share a bounded consistent snapshot."""
from datetime import datetime, timezone
from sqlalchemy import text
from .report_types import MetricReport
from .queries import load_snapshot
from .calculations import calculate


class MetricReportService:
    def __init__(self, engine, *, backend_database_environment=None, clock=None):
        if backend_database_environment not in {None, 'development', 'production', 'test'}:
            raise ValueError('Invalid backend database environment')
        self.engine = engine
        self.backend_database_environment = backend_database_environment
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def build(self, options):
        if options.end > self.clock():
            raise ValueError('Report end cannot be in the future')
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            with conn.begin():
                conn.execute(text('SET TRANSACTION READ ONLY'))
                conn.execute(text("SET LOCAL statement_timeout='5s'"))
                conn.execute(text("SET LOCAL lock_timeout='1s'"))
                conn.execute(text("SET LOCAL idle_in_transaction_session_timeout='10s'"))
                data = load_snapshot(conn, options, self.backend_database_environment)
        return MetricReport(options=options, rows=calculate(options, data))
