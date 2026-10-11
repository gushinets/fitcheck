from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FITCHECK_", extra="forbid")
    env: Literal["dev", "test", "production"] = "dev"
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_origins: list[str] = Field(default_factory=list)
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    api_body_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)

    @field_validator("allowed_origins")
    @classmethod
    def exact_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            url = urlsplit(value)
            if ("*" in value or url.scheme not in {"http", "https", "chrome-extension"}
                    or not url.hostname or url.username or url.password or url.path
                    or url.query or url.fragment or value != f"{url.scheme}://{url.netloc}"):
                raise ValueError("Only exact HTTP(S) or extension origins are allowed")
            _ = url.port
        return list(dict.fromkeys(values))
