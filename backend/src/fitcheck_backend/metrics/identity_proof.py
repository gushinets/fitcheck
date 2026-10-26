"""A verified Next relay assertion, never browser account/guest identity."""
import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, StrictInt, ValidationError
from ..contracts.domain import DTO


class VisitorProof(DTO):
    v: Annotated[StrictInt, Field(ge=1,le=1)]
    environment: Literal['test','development','production']
    visitor_id: UUID
    cookie_issued_at: Annotated[StrictInt, Field(ge=0)]
    issued_at: Annotated[StrictInt, Field(ge=0)]
    expires_at: Annotated[StrictInt, Field(ge=0)]
    request_id: UUID
    method: Literal['POST']
    path: Literal['/v1/auth/register','/v1/auth/login','/v1/guest-claims']


@dataclass(frozen=True)
class VisitorContext:
    visitor_id: UUID
    cookie_issued_at: datetime
    received_at: datetime
    request_id: UUID


def verify_visitor_proof(value, settings, *, method, path, now):
    if not settings.metrics_configured or not isinstance(value,str) or len(value)>2048:
        return None
    if re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}',value) is None:
        return None
    encoded,mac=value.split('.')
    expected=hmac.new(settings.metrics_ingest_key.get_secret_value().encode(),
        ('fitcheck:metrics:identity:v1:'+encoded).encode(),hashlib.sha256).digest()
    expected=base64.urlsafe_b64encode(expected).decode().rstrip('=')
    if not hmac.compare_digest(mac,expected):
        return None
    try:
        data=VisitorProof.model_validate_json(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        ms=int(now.timestamp()*1000)
        if (data.method!=method or data.path!=path or data.environment!=settings.metrics_environment
                or data.visitor_id.int==0 or data.expires_at!=data.issued_at+120000
                or not data.cookie_issued_at<=data.issued_at<=ms<data.expires_at
                or ms>=data.cookie_issued_at+180*86400000):
            return None
        return VisitorContext(data.visitor_id,datetime.fromtimestamp(data.cookie_issued_at/1000,UTC),now,data.request_id)
    except (ValidationError,ValueError,OverflowError):
        return None
