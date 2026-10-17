from sqlalchemy import select,func
from pydantic import ValidationError
from ..contracts.imports import parse_import_row,normalize_profile,storage_safe,usable_external_id
from ..contracts.domain import FreelancerProfile
from ..contracts.jobs import ImportReference
from ..storage.models import Job
from ..storage.payloads import canonical_hash
from ..jobs.errors import JobError


def sanitized_input(request):
    value=request.model_dump(mode='json')
    if request.profile is not None:
        try:
            if not storage_safe(request.profile):raise ValueError('Invalid stored text')
            value['profile']=FreelancerProfile.model_validate(normalize_profile(request.profile)).model_dump(mode='json')
        except (ValidationError,ValueError):value['profile']={}
    rows=[]
    for raw in request.history:
        try:rows.append(parse_import_row(raw).model_dump(mode='json'))
        except ValidationError:
            external=raw.get('id')
            rows.append({'id':external.strip(),'invalid':True} if usable_external_id(external) else {'invalid':True})
    value['history']=rows
    return value


class ImportAdmission:
    def __init__(self,history,settings):self.history,self.settings=history,settings

    def start(self,principal,request,key):
        if not isinstance(key,str) or not 1<=len(key)<=200:raise JobError('invalid_request')
        try:digest=canonical_hash(request.model_dump(mode='json'))
        except (ValueError,TypeError):raise JobError('invalid_request') from None
        safe=sanitized_input(request)
        with self.history.transaction(principal,mutation=True) as s:
            existing=s.scalar(select(Job).where(Job.owner_id==principal.owner_id,Job.type=='import',Job.idempotency_key==key))
            if existing:
                if existing.request_hash!=digest:raise JobError('conflict')
                return ImportReference(importId=str(existing.id))
            active=s.scalar(select(func.count()).select_from(Job).where(Job.owner_id==principal.owner_id,Job.status.in_(['queued','running'])))
            if active>=self.settings.account_max_active_jobs:raise JobError('rate_limited')
            job=Job(owner_id=principal.owner_id,type='import',status='queued',input=safe,idempotency_key=key,request_hash=digest)
            s.add(job);s.flush()
            return ImportReference(importId=str(job.id))
