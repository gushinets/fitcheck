from fastapi import FastAPI
from fitcheck_backend.config import Settings
from fitcheck_backend.api.health import router


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="FitCheck API", version="0.1.0", redirect_slashes=False)
    app.state.settings = settings if settings is not None else Settings()
    app.include_router(router)
    return app
