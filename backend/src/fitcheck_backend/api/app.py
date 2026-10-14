from fastapi import FastAPI
from contextlib import asynccontextmanager
from fitcheck_backend.config import Settings
from fitcheck_backend.api.health import router
from fitcheck_backend.api.errors import install_error_handlers
from fitcheck_backend.api.middleware import RequestBoundaryMiddleware
from fitcheck_backend.api.auth import router as auth_router
from fitcheck_backend.api.profiles import router as profiles_router
from fitcheck_backend.api.extraction import router as extraction_router
from fitcheck_backend.api.jobs import router as jobs_router
from fitcheck_backend.api.runtime import AuthRuntime, MetricsRuntime
from fitcheck_backend.api.metrics import router as metrics_router
from fitcheck_backend.contracts.openapi import security_schemes


def create_app(settings: Settings | None = None, *, auth_runtime: AuthRuntime | None = None, metrics_collector=None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(app):
        runtime = auth_runtime if auth_runtime is not None else (AuthRuntime(configuration) if configuration.auth_enabled else None)
        app.state.auth_runtime = runtime
        metrics = None
        try:
            metrics = (MetricsRuntime(configuration, engine=runtime.engine if runtime is not None else None)
                       if metrics_collector is None and configuration.metrics_configured else None)
            app.state.metrics_collector = metrics_collector if metrics_collector is not None else (metrics.collector if metrics else None)
            yield
        finally:
            if metrics is not None:
                metrics.close()
            if runtime is not None:
                runtime.close()
            app.state.auth_runtime = None
            app.state.metrics_collector = None
    app = FastAPI(title="FitCheck API", version="0.1.0", redirect_slashes=False, lifespan=lifespan)
    app.state.settings = configuration
    app.state.auth_runtime = auth_runtime
    app.state.metrics_collector = metrics_collector
    install_error_handlers(app)
    app.add_middleware(RequestBoundaryMiddleware, max_body_bytes=app.state.settings.api_body_max_bytes, allowed_origins=app.state.settings.allowed_origins)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(profiles_router)
    app.include_router(extraction_router)
    app.include_router(jobs_router)
    app.include_router(metrics_router)
    original_openapi = app.openapi
    def documented_openapi():
        doc = original_openapi()
        doc.setdefault('components', {})['securitySchemes'] = security_schemes()
        for item in doc['paths'].values():
            for operation in item.values():
                operation['responses'].pop('422', None)
        return doc
    app.openapi = documented_openapi
    return app
