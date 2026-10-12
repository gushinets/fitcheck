from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from .models import AnalysisRecord, AnalysisAnnotation
from .payloads import decode_analysis, decode_snapshot


@dataclass(frozen=True)
class CalibrationEntry:
    job_title: str
    predicted_score: int
    corrected_score: int | None
    note: str | None


def get_calibration(session: Session, owner_id: UUID) -> list[CalibrationEntry]:
    rows = session.execute(select(AnalysisRecord, AnalysisAnnotation).outerjoin(
        AnalysisAnnotation, and_(AnalysisAnnotation.analysis_id == AnalysisRecord.id,
            AnalysisAnnotation.owner_id == owner_id)).where(AnalysisRecord.owner_id == owner_id)
        .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc()).limit(10))
    entries = []
    for record, annotation in rows:
        snapshot, analysis = decode_snapshot(record.snapshot), decode_analysis(record.analysis)
        entries.append(CalibrationEntry(snapshot.vacancy.title, analysis.score,
            annotation.corrected_score if annotation else None,
            annotation.note if annotation else None))
    return entries
