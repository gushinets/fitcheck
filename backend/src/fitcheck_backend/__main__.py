import uvicorn
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app


def main() -> None:
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level=settings.log_level, access_log=False)


if __name__ == "__main__":
    main()
