from fastapi import APIRouter, Depends, Request

from ..contracts.resources import ExtractionRequest, ExtractionResponse
from ..contracts.openapi import ERRORS, SECURITY
from .dependencies import required_runtime, verified_principal, validate_account_mutation, client_ip, resolve_identity, validate_identity_mutation
from .errors import ErrorEnvelope
from ..auth.errors import AuthError

router = APIRouter(dependencies=[Depends(required_runtime)],
    responses={status: {'model': ErrorEnvelope, 'description': code} for status, code in ERRORS.items()})


def extraction_principal(request: Request, principal=Depends(resolve_identity)):
    validate_identity_mutation(request, principal)
    if principal.mode=='guest' and not required_runtime(request).settings.guest_enabled:
        raise AuthError('service_unavailable')
    return principal


@router.post('/v1/extractions', response_model=ExtractionResponse, operation_id='extractVacancy',
    openapi_extra={'x-fitcheck-owner-task': 'ANY-647', 'x-fitcheck-implementation': 'implemented',
        'security': SECURITY['identity'],
        'x-fitcheck-cookie-mutation': {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'},
        'parameters': [
            {'name':'Origin', 'in':'header', 'required':True, 'schema':{'type':'string'}},
            {'name':'X-CSRF-Token', 'in':'header', 'required':True, 'schema':{'type':'string'}}]})
def extract_vacancy(body: ExtractionRequest, request: Request, principal=Depends(extraction_principal)):
    return required_runtime(request).extraction.extract(principal, body, client_ip(request))
