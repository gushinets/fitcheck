import uvicorn
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.logging import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level=settings.log_level, log_config=None, access_log=False,
                proxy_headers=bool(settings.trusted_proxy_ips), forwarded_allow_ips=','.join(settings.trusted_proxy_ips))


if __name__ == "__main__":
    main()
