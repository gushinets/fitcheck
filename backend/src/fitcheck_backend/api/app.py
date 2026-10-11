from fastapi import FastAPI
from fitcheck_backend.config import Settings
from fitcheck_backend.api.health import router
from fitcheck_backend.api.errors import install_error_handlers
from fitcheck_backend.api.middleware import RequestBoundaryMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="FitCheck API", version="0.1.0", redirect_slashes=False)
    app.state.settings = settings if settings is not None else Settings()
    install_error_handlers(app)
    app.add_middleware(RequestBoundaryMiddleware, max_body_bytes=app.state.settings.api_body_max_bytes, allowed_origins=app.state.settings.allowed_origins)
    app.include_router(router)
    return app
