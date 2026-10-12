from typing import Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel
from .errors import ErrorEnvelope


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    stage: Literal["foundation", "auth_storage"] = "foundation"
    dependencies: dict[str, str] | None = None


router = APIRouter()


@router.get("/health/live", response_model=HealthResponse, response_model_exclude_none=True, operation_id="healthLive")
async def live(request: Request) -> HealthResponse:
    return HealthResponse(stage='auth_storage' if request.app.state.settings.auth_enabled else 'foundation')


@router.get("/health/ready", response_model=HealthResponse, response_model_exclude_none=True, operation_id="healthReady", responses={503:{'model':ErrorEnvelope,'description':'Database or migration state unavailable'}})
def ready(request: Request) -> HealthResponse:
    if not request.app.state.settings.auth_enabled:
        return HealthResponse()
    from .dependencies import required_runtime
    runtime = required_runtime(request)
    runtime.check_database()
    return HealthResponse(stage='auth_storage', dependencies={'database':'ready','email':'configured' if runtime.mailer.available() else 'unconfigured'})
