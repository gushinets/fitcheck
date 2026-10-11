import uvicorn
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.logging import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level=settings.log_level, access_log=False)


if __name__ == "__main__":
    main()
