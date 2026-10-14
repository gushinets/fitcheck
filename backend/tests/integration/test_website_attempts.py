from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import select
from fitcheck_backend.metrics.contracts import WebsiteAttempt
from fitcheck_backend.metrics.repository import MetricRepository
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import WebsiteProviderAttempt
pytestmark = pytest.mark.integration

def test_attempt_finish_replay_no_double_cost(engine):
    now = utcnow()
    operation = uuid4()
    visitor = uuid4()
    values = [WebsiteAttempt(callId=uuid4(),operationId=operation,subjectId=visitor,
        purpose=purpose,ordinal=ordinal,provider='deepseek',model='deepseek-v4-flash',
        promptVersion='website.v1',policyVersion='grounding.v1',startedAt=now,finishedAt=now,
        state='succeeded',inputTokens=10,outputTokens=2,cost='0.01',currency='USD',costBasis='reported')
        for purpose,ordinal in [('analysis.generate',1),('analysis.audit',2),('analysis.generate',3)]]
    with unit_of_work(engine) as s:
        repo = MetricRepository(s)
        for value in values:
            assert repo.settle_attempt(value,environment='test')
            assert not repo.settle_attempt(value,environment='test')
    with unit_of_work(engine) as s:
        rows = s.scalars(select(WebsiteProviderAttempt)).all()
        assert len(rows) == 3
        assert sum(row.cost for row in rows) == Decimal('0.03')
        assert {row.operation_id for row in rows} == {operation}
