from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..contracts.resources import Preferences, DraftResource
from .base import utcnow
from .models import Preference, Draft
from .payloads import encode_vacancy, decode_vacancy


def get_preferences(session: Session, owner_id: UUID) -> Preferences:
    value = session.get(Preference, owner_id)
    return Preferences(locale=value.locale if value is not None else 'en')


def save_preferences(session: Session, owner_id: UUID, value: Preferences) -> Preferences:
    session.execute(insert(Preference).values(owner_id=owner_id, locale=value.locale)
        .on_conflict_do_update(index_elements=[Preference.owner_id],
            set_={'locale': value.locale, 'updated_at': utcnow()}))
    return value


def get_draft(session: Session, owner_id: UUID) -> DraftResource | None:
    value = session.get(Draft, owner_id)
    if value is None:
        return None
    return DraftResource(vacancy=decode_vacancy(value.vacancy), locale=value.locale)


def save_draft(session: Session, owner_id: UUID, value: DraftResource | None) -> DraftResource | None:
    if value is None:
        session.execute(delete(Draft).where(Draft.owner_id == owner_id))
    else:
        payload = encode_vacancy(value.vacancy)
        session.execute(insert(Draft).values(owner_id=owner_id, vacancy=payload, locale=value.locale)
            .on_conflict_do_update(index_elements=[Draft.owner_id],
                set_={'vacancy': payload, 'locale': value.locale, 'updated_at': utcnow()}))
    return value
