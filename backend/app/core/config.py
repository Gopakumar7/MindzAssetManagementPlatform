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
    cookie_secure_setting: bool = Field(default=False, alias='COOKIE_SECURE')

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
        return self.cookie_secure_setting or self.app_env.casefold() not in {'development', 'dev', 'test'}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
