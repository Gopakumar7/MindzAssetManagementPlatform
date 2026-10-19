from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_env: str = Field(default='development', alias='APP_ENV')
    app_title: str = Field(default='MindZen ALCM / ITAM', alias='APP_TITLE')
    app_version: str = Field(default='0.1.0', alias='APP_VERSION')
    api_prefix: str = Field(default='/api/v1', alias='API_PREFIX')
    database_url: str = Field(default='postgresql+psycopg://mindzen:change_me@localhost:5432/mindzen', alias='DATABASE_URL')
    cors_origins: str = Field(default='http://localhost:4200,http://127.0.0.1:4200', alias='CORS_ORIGINS')
    log_level: str = Field(default='INFO', alias='LOG_LEVEL')
    cookie_secure_setting: bool | None = Field(default=None, alias='COOKIE_SECURE')

    # Alert Schedule and Automation
    alert_schedule_enabled: bool = Field(default=True, alias='ALERT_SCHEDULE_ENABLED')
    alert_schedule_interval_seconds: int = Field(default=3600, alias='ALERT_SCHEDULE_INTERVAL_SECONDS')
    alert_schedule_startup_delay_seconds: int = Field(default=15, alias='ALERT_SCHEDULE_STARTUP_DELAY_SECONDS')
    alert_job_heartbeat_interval_seconds: int = Field(default=60, alias='ALERT_JOB_HEARTBEAT_INTERVAL_SECONDS')
    alert_job_lease_expiry_seconds: int = Field(default=300, alias='ALERT_JOB_LEASE_EXPIRY_SECONDS')

    # Notifications and Email Delivery
    notification_email_enabled: bool = Field(default=False, alias='NOTIFICATION_EMAIL_ENABLED')
    notification_email_mode: str = Field(default='capture', alias='NOTIFICATION_EMAIL_MODE')
    smtp_host: str | None = Field(default=None, alias='SMTP_HOST')
    smtp_port: int = Field(default=587, alias='SMTP_PORT')
    smtp_username: str | None = Field(default=None, alias='SMTP_USERNAME')
    smtp_password: str | None = Field(default=None, alias='SMTP_PASSWORD')
    smtp_use_tls: bool = Field(default=True, alias='SMTP_USE_TLS')
    email_from: str = Field(default='alerts@mindzen.invalid', alias='EMAIL_FROM')

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False,
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]

    @property
    def cookie_secure(self) -> bool:
        if self.cookie_secure_setting is not None:
            return self.cookie_secure_setting

        return self.app_env.casefold() not in {'development', 'dev', 'test'}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
