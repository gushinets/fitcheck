from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    stage: Literal["foundation"] = "foundation"


router = APIRouter()


@router.get("/health/live", response_model=HealthResponse, operation_id="healthLive")
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse, operation_id="healthReady")
async def ready() -> HealthResponse:
    return HealthResponse()
