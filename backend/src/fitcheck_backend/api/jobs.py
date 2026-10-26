from uuid import UUID
import logging
from typing import Annotated
from fastapi import APIRouter,Depends,Header,Request,Path
from ..contracts.jobs import JobAdmissionResource,JobState
from ..contracts.resources import AnalysisStart,AccountAnalysisStart,SkillSuggestionStart
from ..contracts.openapi import ERRORS,SECURITY
from ..jobs.errors import JobError
from .errors import ErrorEnvelope
from .dependencies import required_runtime,verified_principal,validate_account_mutation,client_ip,resolve_identity,validate_identity_mutation

router = APIRouter(dependencies=[Depends(required_runtime)],
    responses={status:{'model':ErrorEnvelope,'description':code} for status,code in ERRORS.items()})


def metadata(mutation=False,access='account'):
    value = {'x-fitcheck-owner-task':'ANY-649','x-fitcheck-implementation':'implemented','security':SECURITY[access]}
    if mutation:
        value['x-fitcheck-cookie-mutation'] = {'originRequired':True,'csrfHeader':'X-CSRF-Token'}
        value['parameters'] = [{'name':'Origin','in':'header','required':True,'schema':{'type':'string'}},
            {'name':'X-CSRF-Token','in':'header','required':False,'schema':{'type':'string'}}]
    return value


def mutation(request: Request,principal=Depends(resolve_identity)):
    validate_identity_mutation(request,principal)
    if principal.mode=='guest' and not request.app.state.settings.guest_enabled:raise JobError('service_unavailable')
    if not request.app.state.settings.jobs_enabled: raise JobError('service_unavailable')
    return principal


def idempotency(request: Request,
        documented: Annotated[str,Header(alias='Idempotency-Key',min_length=1,max_length=200)]):
    values = request.headers.getlist('idempotency-key')
    if len(values) != 1 or not 1 <= len(values[0]) <= 200: raise JobError('invalid_request')
    return values[0]


def log_admission(request, job_id):
    logging.getLogger('fitcheck.jobs').info('job_admitted', extra={'event':'job_admitted',
        'request_id':request.state.request_id,'job_id':str(job_id),'owner_ref':getattr(request.state,'owner_ref',None)})


def admitted(value):
    return JobAdmissionResource(jobId=str(value.job_id),type=value.type,status=value.status)


@router.post('/v1/analysis-jobs',status_code=202,response_model=JobAdmissionResource,
    operation_id='startAnalysis',openapi_extra=metadata(True,access='identity'))
def start_analysis(request: Request,body: AnalysisStart,key=Depends(idempotency)):
    principal=resolve_identity(request,mode=body.root.mode)
    mutation(request,principal)
    value = required_runtime(request).jobs.start_analysis(identity=principal,
        request=body.root,idempotency_key=key,client_ip=client_ip(request))
    log_admission(request,value.job_id)
    return admitted(value)


@router.post('/v1/skill-suggestion-jobs',status_code=202,response_model=JobAdmissionResource,
    operation_id='startSkillSuggestions',openapi_extra=metadata(True,access='identity'))
def start_suggestions(request: Request,body: SkillSuggestionStart,principal=Depends(mutation),key=Depends(idempotency)):
    value = required_runtime(request).jobs.start_suggestions(identity=principal,
        request=body,idempotency_key=key,client_ip=client_ip(request))
    log_admission(request,value.job_id)
    return admitted(value)


@router.get('/v1/jobs/{jobId}',response_model=JobState,operation_id='getJob',openapi_extra=metadata(access='identity'))
def get_job(request: Request,job_id: Annotated[UUID,Path(alias='jobId')],principal=Depends(resolve_identity)):
    return required_runtime(request).job_status.get(owner_id=principal.owner_id,job_id=job_id,identity=principal)
