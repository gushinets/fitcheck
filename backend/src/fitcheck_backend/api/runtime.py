from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from ..config import Settings
from ..storage.database import create_engine
from ..storage.base import utcnow
from ..storage.migrate import schema_head
from ..auth.crypto import AuthCrypto
from ..auth.passwords import PasswordCodec
from ..auth.rate_limit import AuthRateLimiter
from ..auth.mail import SMTPMailer
from ..auth.service import AuthService
from ..auth.email_service import EmailAuthService
from ..auth.access import AccountDeletionService
from ..auth.errors import AuthError
from ..profiles.service import ProfileService
from ..extraction.service import ExtractionService
from ..jobs.admission import JobAdmission
from ..jobs.status import JobStatusReader


class AuthRuntime:
    def __init__(self, settings: Settings, *, engine=None, mailer=None, clock=utcnow):
        if not settings.auth_enabled or settings.auth_secret is None:
            raise ValueError('Authentication runtime requires enabled settings')
        self.settings, self.clock = settings, clock
        self._owns_engine = engine is None
        self.engine = engine if engine is not None else create_engine(settings)
        self.crypto = AuthCrypto(bytes.fromhex(settings.auth_secret.get_secret_value()), clock)
        passwords = PasswordCodec()
        self.limiter = AuthRateLimiter(self.engine, self.crypto, clock)
        self.mailer = mailer if mailer is not None else SMTPMailer(settings)
        metrics_environment = settings.metrics_environment if settings.metrics_enabled else None
        self.auth = AuthService(self.engine, self.crypto, passwords, self.limiter, self.mailer, clock, metrics_environment=metrics_environment)
        self.email = EmailAuthService(self.engine, self.crypto, passwords, self.limiter, self.mailer, clock, metrics_environment=metrics_environment)
        self.deletion = AccountDeletionService(self.engine, passwords, self.limiter, clock, metrics_environment=metrics_environment)
        self.profiles = ProfileService(self.engine, clock, metrics_environment=metrics_environment)
        self.extraction = ExtractionService(self.limiter)
        self.jobs = JobAdmission(self.engine,self.limiter,model=settings.open_ai_model,metrics_environment=metrics_environment)
        self.job_status = JobStatusReader(self.engine)

    def close(self):
        if self._owns_engine:
            self.engine.dispose()

    def check_database(self):
        try:
            with self.engine.connect() as c:
                revision = c.scalar(text('SELECT version_num FROM alembic_version'))
            if revision != schema_head():
                raise AuthError('service_unavailable')
        except SQLAlchemyError:
            raise AuthError('service_unavailable') from None


class MetricsRuntime:
    def __init__(self, settings: Settings, *, engine=None, clock=utcnow):
        from ..metrics.collector import MetricsCollector
        self._owns_engine = engine is None
        self.engine = engine if engine is not None else create_engine(settings)
        self.collector = MetricsCollector(self.engine, settings, clock)

    def close(self):
        if self._owns_engine:
            self.engine.dispose()
