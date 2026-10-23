from hmac import compare_digest
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Path
from ..metrics.contracts import WebsiteBatch, AttemptBatch, IngestResult, DeleteResult
from ..contracts.openapi import ERRORS
from .errors import ApiError, ErrorEnvelope


def collector(request: Request):
    value = request.app.state.metrics_collector
    settings = request.app.state.settings
    if value is None or not settings.metrics_configured:
        raise ApiError(503, 'service_unavailable', 'Service unavailable')
    if request.headers.get('origin') is not None:
        raise ApiError(403, 'forbidden', 'Forbidden')
    keys = request.headers.getlist('x-fitcheck-metrics-key')
    if len(keys) != 1 or not compare_digest(keys[0].encode(), settings.metrics_ingest_key.get_secret_value().encode()):
        raise ApiError(401, 'unauthenticated', 'Unauthenticated')
    value.limiter.enforce()
    return value


router = APIRouter(responses={status:{'model':ErrorEnvelope,'description':code} for status,code in ERRORS.items()})
metadata = {'x-fitcheck-owner-task':'fitcheck-metrics', 'x-fitcheck-implementation':'implemented',
            'security':[{'metricsBridge':[]}], 'x-fitcheck-internal':True}


@router.post('/internal/metrics/events', response_model=IngestResult, operation_id='ingestWebsiteMetrics', openapi_extra=metadata)
def events(body: WebsiteBatch, request: Request, value=Depends(collector)):
    from ..auth.errors import AuthError
    from ..guests.sessions import guest_cookie_name
    runtime = request.app.state.auth_runtime
    identity = None
    if runtime is not None and any(event.properties.get('flow') == 'demo' for event in body.events):
        name = guest_cookie_name(runtime.settings)
        cookies = [item.strip() for item in request.headers.get('cookie', '').split(';')
                   if item.strip().startswith(name + '=')]
        if len(cookies) == 1:
            try:
                identity = runtime.guests.resolve(cookies[0][len(name)+1:], allow_claim_receipt=True)
            except AuthError as exc:
                if exc.code != 'unauthenticated':
                    raise
    return value.ingest(body, guest_identity=identity)


@router.post('/internal/metrics/attempts', response_model=IngestResult, operation_id='ingestWebsiteAttempts', openapi_extra=metadata)
def attempts(body: AttemptBatch, value=Depends(collector)):
    return value.ingest_attempts(body)


@router.delete('/internal/metrics/visitors/{visitorId}', response_model=DeleteResult, operation_id='deleteWebsiteVisitorMetrics', openapi_extra=metadata)
def visitor(visitor_id: Annotated[UUID,Path(alias='visitorId')], value=Depends(collector)):
    return DeleteResult(deleted=value.delete_visitor(visitor_id))
