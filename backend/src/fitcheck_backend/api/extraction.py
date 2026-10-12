from fastapi import APIRouter, Depends, Request

from ..contracts.resources import ExtractionRequest, ExtractionResponse
from ..contracts.openapi import ERRORS, SECURITY
from .dependencies import required_runtime, verified_principal, validate_account_mutation, client_ip
from .errors import ErrorEnvelope

router = APIRouter(dependencies=[Depends(required_runtime)],
    responses={status: {'model': ErrorEnvelope, 'description': code} for status, code in ERRORS.items()})


def extraction_principal(request: Request, principal=Depends(verified_principal)):
    validate_account_mutation(request, principal)
    return principal


@router.post('/v1/extractions', response_model=ExtractionResponse, operation_id='extractVacancy',
    openapi_extra={'x-fitcheck-owner-task': 'ANY-647', 'x-fitcheck-implementation': 'implemented',
        'security': SECURITY['account'],
        'x-fitcheck-cookie-mutation': {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'},
        'parameters': [
            {'name':'Origin', 'in':'header', 'required':True, 'schema':{'type':'string'}},
            {'name':'X-CSRF-Token', 'in':'header', 'required':True, 'schema':{'type':'string'}}]})
def extract_vacancy(body: ExtractionRequest, request: Request, principal=Depends(extraction_principal)):
    return required_runtime(request).extraction.extract(principal, body, client_ip(request))
