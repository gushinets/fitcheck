from logging.config import dictConfig
from datetime import datetime, timezone
import json
import logging
import math
import re


class JsonFormatter(logging.Formatter):
    """Allowlisted technical fields only. Never format arguments or exceptions."""
    def format(self, record):
        events = {'http_request', 'job_admitted', 'job_started', 'job_finished', 'worker_unavailable'}
        event = getattr(record, 'event', None)
        value = {'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                 'level': record.levelname, 'event': event if event in events else 'application_log'}
        known = {'Worker startup/runtime unavailable':'worker_unavailable',
                 'Worker health marker temporarily unavailable':'worker_health_unavailable',
                 'Worker health path belongs to another live worker':'worker_health_unavailable',
                 'worker iteration unavailable':'worker_unavailable'}
        if isinstance(record.msg,str) and record.msg in known:
            value.update(event=known[record.msg],message=record.msg)
        for field in ('request_id', 'job_id'):
            candidate = getattr(record, field, None)
            if isinstance(candidate, str) and re.fullmatch(r'[0-9a-f-]{36}', candidate): value[field] = candidate
        owner = getattr(record, 'owner_ref', None)
        if isinstance(owner, str) and re.fullmatch(r'[0-9a-f]{24}', owner): value['owner_ref'] = owner
        method = getattr(record, 'method', None)
        if method in {'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'}: value['method'] = method
        path = getattr(record, 'route', None)
        if isinstance(path, str) and len(path) <= 200 and re.fullmatch(r'/[a-zA-Z0-9_/{}/-]*', path): value['route'] = path
        status = getattr(record, 'status', None)
        if type(status) is int and 100 <= status <= 599: value['status'] = status
        duration = getattr(record, 'duration_ms', None)
        if isinstance(duration, (int, float)) and math.isfinite(duration) and duration >= 0: value['duration_ms'] = round(duration, 2)
        outcome = getattr(record, 'outcome', None)
        if outcome in {'succeeded', 'failed', 'lease_lost', 'interrupted'}: value['outcome'] = outcome
        # Unknown logger messages and exception text may contain provider content.
        return json.dumps(value, ensure_ascii=True, allow_nan=False)


def configure_logging(level: str) -> None:
    """Configure application and server logs without arbitrary exception text."""
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"fitcheck": {"()": JsonFormatter}},
        "handlers": {"fitcheck": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "fitcheck"}},
        "loggers": {name: {"level": level.upper(), "handlers": ["fitcheck"], "propagate": False}
                    for name in ('fitcheck', 'uvicorn.error')},
    })
