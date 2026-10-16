from typing import Literal
from urllib.parse import urlsplit
import ipaddress
import re
from pydantic import Field, SecretStr, field_validator, model_validator
from email_validator import validate_email, EmailNotValidError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FITCHECK_", extra="forbid", hide_input_in_errors=True, populate_by_name=True)
    database_url: SecretStr | None = None
    open_ai_key: SecretStr | None = Field(default=None, validation_alias='OPEN_AI_KEY')
    open_ai_model: Literal['gpt-6-luna'] = Field(default='gpt-6-luna', validation_alias='OPEN_AI_MODEL')
    pool_size: int = Field(default=2, ge=1, le=20)
    max_overflow: int = Field(default=3, ge=0, le=20)
    pool_timeout_seconds: int = Field(default=5, ge=1, le=60)
    statement_timeout_ms: int = Field(default=15000, ge=1, le=300000)
    env: Literal["dev", "test", "production"] = "dev"
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_origins: list[str] = Field(default_factory=list)
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    api_body_max_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    auth_enabled: bool = False
    metrics_enabled: bool = False
    metrics_environment: Literal["development", "production", "test"] | None = None
    metrics_database_environment: Literal["development", "production", "test"] | None = None
    metrics_ingest_key: SecretStr | None = None
    metrics_campaign_codes: list[str] = Field(default_factory=list)
    jobs_enabled: bool = False
    auth_secret: SecretStr | None = None
    auth_web_base_url: str | None = None
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_security: Literal['smtps', 'starttls'] | None = None

    @field_validator('metrics_campaign_codes')
    @classmethod
    def valid_campaigns(cls, values):
        if len(values) > 100 or any(re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value) is None for value in values):
            raise ValueError('Invalid campaign allowlist')
        return list(dict.fromkeys(values))

    @property
    def metrics_configured(self):
        return bool(self.metrics_enabled and self.database_url is not None and self.metrics_environment is not None
                    and self.metrics_ingest_key is not None and self.metrics_ingest_key.get_secret_value())

    @field_validator('auth_secret')
    @classmethod
    def valid_secret(cls, value):
        if value is not None and re.fullmatch(r'(?:[0-9a-fA-F]{2}){32,}', value.get_secret_value()) is None:
            raise ValueError('Invalid authentication secret')
        return value

    @field_validator('trusted_proxy_ips')
    @classmethod
    def valid_proxies(cls, values):
        for value in values:
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError:
                raise ValueError('Expected an explicit trusted proxy IP or CIDR') from None
        return values

    @model_validator(mode='after')
    def auth_configuration(self):
        if self.auth_enabled and (self.database_url is None or self.auth_secret is None or self.auth_web_base_url is None):
            raise ValueError('Authentication requires database, secret and web base URL')
        if self.auth_web_base_url is not None:
            p = urlsplit(self.auth_web_base_url)
            if (p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password
                    or p.path or p.query or p.fragment or self.auth_web_base_url != f'{p.scheme}://{p.netloc}'
                    or self.env == 'production' and p.scheme != 'https'):
                raise ValueError('Invalid authentication web base URL')
            _ = p.port
        smtp = [self.smtp_host, self.smtp_port, self.smtp_username, self.smtp_password, self.smtp_from, self.smtp_security]
        if any(x is not None for x in smtp) and not all(x is not None and str(x) for x in smtp):
            raise ValueError('SMTP settings must be complete')
        if self.smtp_host is not None:
            if any(c.isspace() or ord(c) < 32 for c in self.smtp_host) or any(c in self.smtp_host for c in '/@?#'):
                raise ValueError('Invalid SMTP host')
            try:
                validate_email(self.smtp_from, check_deliverability=False)
            except EmailNotValidError:
                raise ValueError('Invalid SMTP sender') from None
            if '\r' in self.smtp_from or '\n' in self.smtp_from:
                raise ValueError('Invalid SMTP sender')
        return self

    @field_validator("allowed_origins")
    @classmethod
    def exact_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            url = urlsplit(value)
            if ("*" in value or url.scheme not in {"http", "https"}
                    or not url.hostname or url.username or url.password or url.path
                    or url.query or url.fragment or value != f"{url.scheme}://{url.netloc}"):
                raise ValueError("Only exact HTTP(S) origins are allowed")
            _ = url.port
        return list(dict.fromkeys(values))
