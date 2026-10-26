from fastapi import APIRouter,Depends,Request
from ..contracts.quotas import QuotaResource
from .dependencies import resolve_identity,required_runtime
from .errors import ErrorEnvelope
from ..contracts.openapi import ERRORS,SECURITY
router=APIRouter(dependencies=[Depends(required_runtime)],responses={s:{'model':ErrorEnvelope,'description':c} for s,c in ERRORS.items()})


@router.get('/v1/quota',response_model=QuotaResource,operation_id='getQuota',
    openapi_extra={'x-fitcheck-owner-task':'ANY-651','security':SECURITY['identity']})
def get_quota(request: Request,identity=Depends(resolve_identity)):
    return required_runtime(request).quotas.get(identity)
