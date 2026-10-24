"""Archive verified result/job facts atomically before technical pruning."""
from datetime import timedelta
from sqlalchemy import select, case, exists, cast, String, or_, literal_column, text
from sqlalchemy.dialects.postgresql import insert
from ..storage.models import AnalysisRecord, Job
from ..storage.analysis_operation import AnalysisOperationProof
from ..storage.metrics import MetricJournal


def retained_result_reference(analysis_id,cutoff):
    # This only retains existing structural proof; it never proves a view or
    # creates an association. Keep its basis while a retained observation needs
    # it, including a first view long after the job originally completed.
    return exists().where(
        # Static SQL matches the partial expression index even for prepared plans.
        text("metric_journal.source='website_client' AND metric_journal.name IN ('analysis_result_viewed','feedback_saved')"),
        cast(MetricJournal.properties.op('->>')(literal_column("'resultId'")),String)==cast(analysis_id,String),
        MetricJournal.received_at>=cutoff)


def archive_analysis_operations(session,job_ids,now):
    mode=Job.input['mode'].as_string()
    statement=select(AnalysisRecord.id,Job.id,Job.created_at,Job.finished_at,
        case((mode.in_(['account','guest']),mode),else_=None)).join(Job,
        (Job.id==AnalysisRecord.job_id)&(Job.owner_id==AnalysisRecord.owner_id))\
        .where(Job.id.in_(job_ids),Job.type=='analysis',Job.status=='succeeded',
               AnalysisRecord.job_type=='analysis',or_(Job.finished_at>=now-timedelta(days=180),
                   retained_result_reference(AnalysisRecord.id,now-timedelta(days=180))))
    # Only an existing same-owner successful job/result pair can create proof.
    # No job FK: technical deletion leaves evidence; analysis deletion cascades.
    session.execute(insert(AnalysisOperationProof).from_select(
        ['analysis_id','job_id','job_created_at','finished_at','mode'],statement).on_conflict_do_nothing())
