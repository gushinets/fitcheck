from contextlib import contextmanager

from pydantic import ValidationError
from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from .cursor import HistoryCursor
from ..guests.types import AccessIdentity
from ..storage.guest_repository import require_identity
from ..auth.access import require_verified
from ..auth.errors import AuthError
from ..auth.service import active_session
from ..contracts.resources import HistoryPage
from ..jobs.errors import JobError
from ..storage.auth_repository import AuthRepository
from ..storage.job_queue import job_transaction
from ..storage.history_repository import history_query, analysis_resource, status_expression
from ..storage.models import Owner, User, AnalysisRecord, AnalysisAnnotation, VacancyRecord


class HistoryService:
    def __init__(self, engine, clock, secret):
        self.engine, self.clock = engine, clock
        self.cursor = HistoryCursor(secret)

    @contextmanager
    def transaction(self, principal, *, mutation=False):
        if not isinstance(principal,AccessIdentity): require_verified(principal)
        try:
            with job_transaction(self.engine) as session:
                if isinstance(principal,AccessIdentity):
                    require_identity(session,principal,self.clock())
                    yield session
                    return
                if mutation:
                    session.scalar(select(Owner).where(Owner.id == principal.owner_id).with_for_update())
                repo = AuthRepository(session)
                user = repo.lock_user(principal.user_id) if mutation else session.get(User, principal.user_id)
                if user is None or user.owner_id != principal.owner_id:
                    raise AuthError('unauthenticated')
                if user.email_verified_at is None:
                    raise AuthError('email_not_verified')
                active_session(repo, principal, self.clock())
                yield session
        except (SQLAlchemyError, ValidationError, ValueError):
            raise JobError('service_unavailable') from None

    @staticmethod
    def required(session, owner_id, analysis_id):
        row = session.execute(history_query(owner_id).where(AnalysisRecord.id == analysis_id)).first()
        if row is None:
            raise JobError('not_found')
        return row

    def get(self, principal, analysis_id):
        with self.transaction(principal) as session:
            return analysis_resource(*self.required(session, principal.owner_id, analysis_id))

    def list(self, principal, *, limit=20, cursor=None, verdict=None, application_status=None, sort='newest'):
        scope = [str(principal.owner_id), verdict, application_status, sort]
        position = self.cursor.decode(cursor, scope) if cursor is not None else None
        with self.transaction(principal) as session:
            query = history_query(principal.owner_id)
            if verdict is not None:
                query = query.where(AnalysisRecord.analysis['status'].astext == verdict)
            if application_status is not None:
                query = query.where(status_expression() == application_status)
            key = tuple_(AnalysisRecord.created_at, AnalysisRecord.id)
            if position is not None:
                query = query.where(key < position if sort == 'newest' else key > position)
            columns = (AnalysisRecord.created_at, AnalysisRecord.id)
            query = query.order_by(*(c.desc() if sort == 'newest' else c.asc() for c in columns))
            rows = session.execute(query.limit(limit + 1)).all()
            more, rows = len(rows) > limit, rows[:limit]
            next_cursor = self.cursor.encode(scope, rows[-1][0].created_at, rows[-1][0].id) if more else None
            return HistoryPage(items=[analysis_resource(*row) for row in rows], nextCursor=next_cursor, hasMore=more)

    def annotate(self, principal, analysis_id, *, feedback=..., application_status=None):
        with self.transaction(principal, mutation=True) as session:
            record, annotation, revision = self.required(session, principal.owner_id, analysis_id)
            if annotation is None:
                annotation = AnalysisAnnotation(owner_id=principal.owner_id, analysis_id=analysis_id)
                session.add(annotation)
            if feedback is not ...:
                annotation.corrected_score = feedback.corrected_score if feedback else None
                annotation.note = feedback.note if feedback else None
                annotation.feedback_created_at = self.clock() if feedback else None
            if application_status is not None:
                annotation.application_status = application_status
            annotation.updated_at = self.clock()
            session.flush()

    def clear(self, principal):
        with self.transaction(principal, mutation=True) as session:
            session.execute(delete(AnalysisRecord).where(AnalysisRecord.owner_id == principal.owner_id))
            # Preserve vacancies still referenced by a concurrently completed job.
            referenced = select(AnalysisRecord.id).where(AnalysisRecord.vacancy_id == VacancyRecord.id).exists()
            session.execute(delete(VacancyRecord).where(VacancyRecord.owner_id == principal.owner_id, ~referenced))
