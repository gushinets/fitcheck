from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='FITCHECK_WORKER_',extra='forbid',hide_input_in_errors=True)
    poll_interval: float = Field(default=1,gt=0,allow_inf_nan=False)
    lease_seconds: float = Field(default=150,ge=150,allow_inf_nan=False)
    heartbeat_seconds: float = Field(default=20,gt=0,allow_inf_nan=False)
    drain_seconds: float = Field(default=130,gt=0,le=130,allow_inf_nan=False)
    health_path: str = '/tmp/fitcheck-worker-health.json'
    metrics_host: str = '127.0.0.1'
    metrics_port: int = Field(default=0,ge=0,le=65535)

    @model_validator(mode='after')
    def valid_timing(self):
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError('Heartbeat must be shorter than lease')
        return self
