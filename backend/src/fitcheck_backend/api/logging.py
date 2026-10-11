from logging.config import dictConfig


def configure_logging(level: str) -> None:
    """Configure only the application namespace; Uvicorn owns its server logs."""
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"fitcheck": {"format": "%(levelname)s %(name)s %(message)s"}},
        "handlers": {"fitcheck": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "fitcheck"}},
        "loggers": {"fitcheck": {"level": level.upper(), "handlers": ["fitcheck"], "propagate": False}},
    })
