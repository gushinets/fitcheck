from datetime import UTC,timedelta
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.dialects.postgresql import insert
from .models import Owner,Guest,Job,ProviderCall,BudgetWindow,CallReservation
from ..quotas.errors import QuotaError


class BudgetRepository:
    def __init__(self,session):self.s=session

    def reserve(self,attempt,bounds,*,policy,now):
        owner=self.s.scalar(select(Owner).where(Owner.id==attempt.owner_id).with_for_update())
        if owner is None:raise ValueError('Invalid owner ownership')
        guest=self.s.scalar(select(Guest).where(Guest.owner_id==owner.id)) if owner.kind=='guest' else None
        if owner.kind=='guest' and (guest is None or guest.expires_at<=now or guest.claimed_by_user_id is not None):
            raise QuotaError('budget_exceeded')
        job=None
        if attempt.job_id is not None:
            job=self.s.scalar(select(Job).where(Job.id==attempt.job_id).with_for_update())
            if job is None or job.owner_id!=owner.id:raise ValueError('Invalid job ownership')
            if attempt.execution_token is not None and (job.status!='running' or job.lease_token!=attempt.execution_token or job.lease_expires_at is None or job.lease_expires_at<=now):
                raise ValueError('Invalid execution lease')
        start=now.astimezone(UTC).replace(hour=0,minute=0,second=0,microsecond=0);end=start+timedelta(days=1)
        kind='suggestions' if attempt.operation=='skill_suggestions' else 'analysis'
        limits=(job.input or {}).get('limits',{}) if job else {}
        # v1 jobs have no frozen limits: safe defaults are snapshotted on first send.
        calls=limits.get('calls',getattr(policy,kind+'_calls'))
        tokens=limits.get('tokens',getattr(policy,kind+'_tokens'))
        usd=Decimal(str(limits.get('usd',getattr(policy,kind+'_usd'))))
        descriptors=[('deployment','daily',start,end,None,2147483647,2147483647,policy.deployment_daily_usd),
            ('owner',str(owner.id),guest.created_at if guest else start,guest.expires_at if guest else end,owner.id,2147483647,2147483647,policy.guest_usd if guest else policy.account_daily_usd),
            ('job',str(job.id if job else attempt.operation_id),job.created_at if job else start,
             job.created_at+timedelta(days=36500) if job else end,owner.id,calls,tokens,usd)]
        windows=[]
        for scope,key,begin,expiry,oid,lc,lt,lu in sorted(descriptors,key=lambda x:(x[0],x[1],x[2])):
            self.s.execute(insert(BudgetWindow).values(scope=scope,scope_key=key,window_start=begin,expires_at=expiry,owner_id=oid,limit_calls=lc,limit_tokens=lt,limit_usd=lu,calls=0,exposure_tokens=0,exposure_usd=0).on_conflict_do_nothing(index_elements=['scope','scope_key','window_start']))
            window=self.s.scalar(select(BudgetWindow).where(BudgetWindow.scope==scope,BudgetWindow.scope_key==key,BudgetWindow.window_start==begin).with_for_update().execution_options(populate_existing=True))
            if (window.calls+1>window.limit_calls or window.exposure_tokens+bounds.input_tokens+bounds.output_tokens>window.limit_tokens or window.exposure_usd+bounds.usd>window.limit_usd):
                raise QuotaError('budget_exceeded')
            windows.append(window)
        row=ProviderCall(owner_id=owner.id,job_id=attempt.job_id,request_key=f'{attempt.operation_id}:{attempt.physical_attempt}',provider=attempt.provider,model=attempt.model,operation=attempt.operation,attempt=attempt.physical_attempt,semantic_attempt=attempt.semantic_attempt,transport_attempt=attempt.transport_attempt,prompt_version=attempt.prompt_version,schema_version=attempt.schema_version,policy_version=attempt.policy_version,execution_token=attempt.execution_token,state='started')
        self.s.add(row);self.s.flush()
        for window in windows:
            window.calls+=1;window.exposure_tokens+=bounds.input_tokens+bounds.output_tokens;window.exposure_usd+=bounds.usd
            self.s.add(CallReservation(provider_call_id=row.id,window_id=window.id,input_tokens=bounds.input_tokens,output_tokens=bounds.output_tokens,usd=bounds.usd,rate_version=bounds.rate_version))
        self.s.flush();return row.id

    def settle(self,call_id,*,reply,outcome,now):
        # Caller locks owner/job first, then these windows, then provider row.
        rows=self.s.scalars(select(CallReservation).where(CallReservation.provider_call_id==call_id)).all()
        ids=[r.window_id for r in rows]
        windows={w.id:w for w in self.s.scalars(select(BudgetWindow).where(BudgetWindow.id.in_(ids)).order_by(BudgetWindow.scope,BudgetWindow.scope_key,BudgetWindow.window_start).with_for_update().execution_options(populate_existing=True))}
        rows=self.s.scalars(select(CallReservation).where(CallReservation.provider_call_id==call_id).with_for_update().execution_options(populate_existing=True)).all()
        for row in rows:
            if row.status!='reserved':continue
            known=(outcome!='unknown' and reply.cost_basis=='estimated' and reply.currency=='USD' and reply.cost is not None and reply.cost.is_finite() and 0<=reply.cost<=row.usd and reply.rate_version==row.rate_version and reply.service_tier=='default' and reply.processing_region=='global' and reply.response_model=='gpt-6-luna' and type(reply.input_tokens) is int and type(reply.output_tokens) is int and 0<=reply.input_tokens<=row.input_tokens and 0<=reply.output_tokens<=row.output_tokens)
            row.status='settled' if known else 'unknown'
            if known:
                w=windows[row.window_id];w.exposure_usd-=row.usd-reply.cost
                w.exposure_tokens-=row.input_tokens+row.output_tokens-reply.input_tokens-reply.output_tokens
        self.s.flush()
