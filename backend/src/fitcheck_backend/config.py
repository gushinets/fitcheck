from typing import Literal
from urllib.parse import urlsplit
import ipaddress
import re
from pydantic import Field, SecretStr, field_validator, model_validator
from email_validator import validate_email, EmailNotValidError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FITCHECK_", extra="forbid", hide_input_in_errors=True)
    database_url: SecretStr | None = None
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
    auth_secret: SecretStr | None = None
    auth_web_base_url: str | None = None
    auth_extension_redirect_uris: list[str] = Field(default_factory=list)
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_security: Literal['smtps', 'starttls'] | None = None

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

    @field_validator('auth_extension_redirect_uris')
    @classmethod
    def valid_redirects(cls, values):
        for value in values:
            p = urlsplit(value)
            if (p.scheme != 'https' or not p.hostname or re.fullmatch(r'[a-p]{32}\.chromiumapp\.org', p.hostname) is None
                    or p.username or p.password or p.port or p.query or p.fragment or not p.path.startswith('/')
                    or value != f'https://{p.hostname}{p.path}' or any(c.isspace() or ord(c) < 32 for c in value)):
                raise ValueError('Expected an exact extension HTTPS callback')
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
            if ("*" in value or url.scheme not in {"http", "https", "chrome-extension"}
                    or not url.hostname or url.username or url.password or url.path
                    or url.query or url.fragment or value != f"{url.scheme}://{url.netloc}"):
                raise ValueError("Only exact HTTP(S) or extension origins are allowed")
            _ = url.port
        return list(dict.fromkeys(values))
