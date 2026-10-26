from typing import Annotated
from uuid import UUID
from fastapi import APIRouter,Depends,Path,Request
from ..contracts.imports import LocalImportRequest
from ..contracts.jobs import ImportReference,ImportState
from ..contracts.openapi import ERRORS
from ..jobs.errors import JobError
from .errors import ErrorEnvelope
from .dependencies import required_runtime,verified_principal,validate_account_mutation
from .jobs import idempotency,log_admission
from .history import metadata

router=APIRouter(dependencies=[Depends(required_runtime)],responses={status:{'model':ErrorEnvelope,'description':code} for status,code in ERRORS.items()})


def import_metadata(mutation=False):
    return metadata(mutation)|{'x-fitcheck-owner-task':'ANY-652'}


def mutation(request:Request,principal=Depends(verified_principal)):
    validate_account_mutation(request,principal)
    if not request.app.state.settings.jobs_enabled:raise JobError('service_unavailable')
    return principal


@router.post('/v1/import-jobs',status_code=202,response_model=ImportReference,operation_id='startImport',openapi_extra=import_metadata(True))
def start_import(request:Request,body:LocalImportRequest,principal=Depends(mutation),key=Depends(idempotency)):
    value = required_runtime(request).imports.start(principal,body,key)
    log_admission(request,value.import_id)
    return value


@router.get('/v1/import-jobs/{importId}',response_model=ImportState,operation_id='getImport',openapi_extra=import_metadata())
def get_import(request:Request,import_id:Annotated[UUID,Path(alias='importId')],principal=Depends(verified_principal)):
    return required_runtime(request).import_status.get(principal,import_id)
