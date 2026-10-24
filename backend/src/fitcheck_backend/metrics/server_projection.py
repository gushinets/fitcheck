"""Minimal bounded current-domain facts, never raw profiles, notes or tokens."""
from collections import defaultdict
from types import SimpleNamespace
from sqlalchemy import select, func, case
from ..storage.models import AnalysisRecord, AnalysisAnnotation, Job, User, AuthSession
from ..storage.analysis_operation import AnalysisOperationProof as Proof
from ..storage.metric_identity import MetricIdentityTransition as Link
from ..storage.metrics import MetricDemoLink, MetricJournal
from .identity_queries import project_identity
from .queries import bounded, safe_code
from .report_types import AnalysisFact, DemoProof, Operation


def score(value):
    return value if type(value) is int and 0<=value<=100 else None


def load_server_projection(conn,options,data):
    groups=defaultdict(list)
    statement=select(*Link.__table__.columns,AuthSession.id.label('live_session'),
        AuthSession.expires_at.label('live_expiry'),AuthSession.revoked_at.label('live_revocation'))\
        .outerjoin(AuthSession,AuthSession.id==Link.auth_session_id).where(
            Link.environment==options.environment,Link.occurred_at>=data.history_floor,
            Link.occurred_at<options.end).order_by(Link.occurred_at,Link.id)
    for row in bounded(conn,statement):
        values=dict(row)
        auth=(SimpleNamespace(expires_at=values.pop('live_expiry'),revoked_at=values.pop('live_revocation'))
              if values['live_session'] is not None else None)
        for key in ('live_session','live_expiry','live_revocation'):values.pop(key,None)
        link=SimpleNamespace(**values)
        groups[link.visitor_id].append((link,auth))
    data.identities={visitor:project_identity(rows) for visitor,rows in groups.items()}
    statement=select(MetricDemoLink.event_id,MetricDemoLink.guest_owner_id,
        MetricDemoLink.job_id,MetricDemoLink.result_id).join(MetricJournal,MetricJournal.event_id==MetricDemoLink.event_id)\
        .where(MetricDemoLink.environment==options.environment,MetricJournal.environment==options.environment,
               MetricJournal.occurred_at>=data.history_floor,MetricJournal.occurred_at<options.end)
    data.demo_proofs={r['event_id']:DemoProof(**{k:v for k,v in r.items() if k!='event_id'}) for r in bounded(conn,statement)}
    if data.backend_scope_reason is not None:
        return
    # Missing current domain registrations are independent evidence of incomplete
    # delivery, including when an interruption marker could not be persisted.
    observed_registration = select(MetricJournal.event_id).where(
        MetricJournal.source=='backend_server', MetricJournal.environment==options.environment,
        MetricJournal.name=='account_registered', MetricJournal.owner_id==User.owner_id,
        MetricJournal.occurred_at>=options.start, MetricJournal.occurred_at<options.end).exists()
    data.missing_domain_registration_facts = conn.scalar(select(func.count()).select_from(User).where(
        User.created_at>=options.start, User.created_at<options.end, ~observed_registration))
    # Original guest mode survives ownership transfer. Never turn it into a
    # second account-created operation when claim moves the job to a user.
    for row in bounded(conn,select(Job.id,Job.created_at,Job.finished_at,Job.status,
            Job.error['code'].label('error_code')).where(Job.type=='analysis',
            Job.input['mode'].as_string()=='guest',Job.created_at>=data.history_floor,Job.created_at<options.end)):
        finished=row['finished_at'] if row['finished_at'] and row['finished_at']<options.end else None
        data.operations.append(Operation(operation_id=row['id'],subject_id=None,source='backend_server',kind='analysis',
            created_at=row['created_at'],finished_at=finished,state=row['status'] if finished else 'unknown',
            error_code=safe_code(row['error_code']) if finished and row['status']=='failed' else None,provenance='server_guest_domain'))
    statement=select(AnalysisRecord.id.label('analysis_id'),AnalysisRecord.owner_id,
        func.coalesce(Job.id,Proof.job_id).label('job_id'),AnalysisRecord.created_at,
        func.coalesce(Job.finished_at,Proof.finished_at).label('finished_at'),
        func.coalesce(Job.status,case((Proof.job_id.is_not(None),'succeeded'))).label('state'),
        func.coalesce(Job.input['mode'].as_string(),Proof.mode).label('mode'),
        Job.id.label('live_job_id'),Proof.job_created_at.label('archived_job_created_at'),User.id.label('user_id'),AnalysisRecord.analysis['score'].label('predicted_score'),
        AnalysisAnnotation.corrected_score,AnalysisAnnotation.feedback_created_at.label('feedback_at'))\
        .outerjoin(Job,(Job.id==AnalysisRecord.job_id)&(Job.owner_id==AnalysisRecord.owner_id))\
        .outerjoin(Proof,Proof.analysis_id==AnalysisRecord.id)\
        .outerjoin(User,User.owner_id==AnalysisRecord.owner_id)\
        .outerjoin(AnalysisAnnotation,(AnalysisAnnotation.analysis_id==AnalysisRecord.id)&
                   (AnalysisAnnotation.owner_id==AnalysisRecord.owner_id))\
        .where(AnalysisRecord.created_at>=data.history_floor,AnalysisRecord.created_at<options.end)
    for row in bounded(conn,statement):
        values=dict(row);values['account_owned']=values.pop('user_id') is not None
        live_job=values.pop('live_job_id');archived_created=values.pop('archived_job_created_at')
        if live_job is None and values['job_id'] is not None and data.history_floor<=archived_created<options.end:
            finished=values['finished_at'] if values['finished_at']<options.end else None
            data.operations.append(Operation(operation_id=values['job_id'],
                subject_id=values['owner_id'] if values['account_owned'] and values['mode']!='guest' else None,
                source='backend_server',kind='analysis',created_at=archived_created,finished_at=finished,
                state='succeeded' if finished else 'unknown',
                provenance='server_guest_domain' if values['mode']=='guest' else 'deployment_database_scope'))
        values['predicted_score']=score(values['predicted_score'])
        values['corrected_score']=score(values['corrected_score'])
        data.analyses.append(AnalysisFact(**values))
