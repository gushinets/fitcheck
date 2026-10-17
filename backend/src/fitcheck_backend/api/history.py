from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response

from ..contracts.jobs import JobReference
from ..contracts.resources import AnalysisResource, HistoryPage, FeedbackResponse, ApplicationStatus, ApplicationStatusUpdate
from ..contracts.openapi import ERRORS, SECURITY
from .dependencies import required_runtime, verified_principal, validate_account_mutation, client_ip
from .errors import ErrorEnvelope, ApiError
from .jobs import idempotency, mutation as job_mutation

router = APIRouter(dependencies=[Depends(required_runtime)],
    responses={status: {'model': ErrorEnvelope, 'description': code} for status, code in ERRORS.items()})
AnalysisId = Annotated[UUID, Path(alias='analysisId')]


def metadata(mutation=False):
    value = {'x-fitcheck-owner-task': 'ANY-650', 'x-fitcheck-implementation': 'implemented', 'security': SECURITY['account']}
    if mutation:
        value['x-fitcheck-cookie-mutation'] = {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'}
        value['parameters'] = [{'name': 'Origin', 'in': 'header', 'required': True, 'schema': {'type': 'string'}},
            {'name': 'X-CSRF-Token', 'in': 'header', 'required': False, 'schema': {'type': 'string'}}]
    return value


def mutation(request: Request, principal=Depends(verified_principal)):
    validate_account_mutation(request, principal)
    return principal


@router.get('/v1/analyses/{analysisId}', response_model=AnalysisResource,
    operation_id='getAnalysis', openapi_extra=metadata())
def get_analysis(request: Request, analysis_id: AnalysisId, principal=Depends(verified_principal)):
    return required_runtime(request).history.get(principal, analysis_id)


@router.get('/v1/history', response_model=HistoryPage, operation_id='getHistory', openapi_extra=metadata())
def get_history(request: Request, principal=Depends(verified_principal),
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2000)] = None,
        verdict: Literal['GO', 'NO_GO'] = None,
        application_status: Annotated[ApplicationStatus | None, Query(alias='applicationStatus')] = None,
        sort: Literal['newest', 'oldest'] = 'newest'):
    return required_runtime(request).history.list(principal, limit=limit, cursor=cursor,
        verdict=verdict, application_status=application_status, sort=sort)


async def required_feedback_body(request: Request):
    if not (await request.body()).strip():
        raise ApiError(400, 'invalid_request', 'Feedback body is required; send null to clear it')


@router.put('/v1/analyses/{analysisId}/feedback', response_model=FeedbackResponse,
    operation_id='updateFeedback', openapi_extra={**metadata(True), 'requestBody': {'required': True}})
def update_feedback(request: Request, analysis_id: AnalysisId,
        body: FeedbackResponse | None = Body(default=None), principal=Depends(mutation),
        _=Depends(required_feedback_body)):
    value = body.root if body is not None else None
    required_runtime(request).history.annotate(principal, analysis_id, feedback=value)
    return FeedbackResponse(value)


@router.put('/v1/analyses/{analysisId}/application-status', response_model=ApplicationStatusUpdate,
    operation_id='updateApplicationStatus', openapi_extra=metadata(True))
def update_application_status(request: Request, analysis_id: AnalysisId,
        body: ApplicationStatusUpdate, principal=Depends(mutation)):
    required_runtime(request).history.annotate(principal, analysis_id, application_status=body.application_status)
    return body


@router.post('/v1/analyses/{analysisId}/reanalyses', status_code=202, response_model=JobReference,
    operation_id='reanalyze', openapi_extra=metadata(True))
def reanalyze(request: Request, analysis_id: AnalysisId, principal=Depends(job_mutation), key=Depends(idempotency)):
    runtime = required_runtime(request)
    value = runtime.jobs.reanalyze(principal=principal, analysis_id=analysis_id,
        idempotency_key=key, client_ip=client_ip(request), clock=runtime.clock)
    return JobReference(jobId=str(value.job_id))


@router.delete('/v1/history', status_code=204, operation_id='clearHistory', openapi_extra=metadata(True))
def clear_history(request: Request, principal=Depends(mutation)):
    required_runtime(request).history.clear(principal)
    return Response(status_code=204)
