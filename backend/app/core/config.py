"""Настройки приложения из переменных окружения (§16.4 техдока)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # Пустые значения из .env (KEY=) считаются незаданными — берётся значение по умолчанию.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    env: Literal["local", "prod", "test"] = "local"
    public_base_url: str = "http://localhost:8080"

    # MAX
    max_bot_token: SecretStr | None = None
    max_bot_username: str = ""
    max_api_base: str = "https://platform-api2.max.ru"
    max_webhook_secret: SecretStr | None = None
    bot_mode: Literal["webhook", "polling"] = "polling"

    # Хранилища
    # Приложение ходит под ролью afisha_app (без DDL, audit_log только INSERT),
    # миграции — под владельцем БД.
    database_url: str = "postgresql+asyncpg://afisha_app:afisha_app@db:5432/afisha"
    migrate_database_url: str | None = None
    app_db_password: SecretStr | None = None
    redis_url: str = "redis://redis:6379/0"
    # Обложки после перекодирования в WebP; отдаются по /media/<uuid>.webp.
    media_dir: str = "/app/media"

    # Доступ
    jwt_secret: SecretStr | None = None
    jwt_ttl_hours: int = 12
    init_data_max_age_s: int = 24 * 3600
    admin_max_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # GigaChat
    gigachat_auth_key: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_oauth_url: str = ""
    gigachat_api_url: str = ""
    gigachat_model: str = "GigaChat"
    llm_daily_token_budget: int = 200_000
    # Путь к сертификату НУЦ Минцифры (russian_trusted_root_ca); пусто — системное хранилище.
    gigachat_ca_bundle: str | None = None

    # Геокодеры и источники
    dadata_api_key: SecretStr | None = None
    dadata_secret_key: SecretStr | None = None
    nominatim_user_agent: str = "afisha-ryadom/1.0"
    proculture_api_key: SecretStr | None = None

    # Режимы
    seed_demo: bool = True
    offline_mode: bool = False
    dev_auth: bool = False
    review_mode: bool = False
    review_accounts: SecretStr | None = None
    log_level: str = "INFO"

    @field_validator("admin_max_user_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.replace(";", ",").split(",") if x.strip()]
        return v

    @model_validator(mode="after")
    def _forbid_dev_auth_in_prod(self) -> "Settings":
        if self.env == "prod" and self.dev_auth:
            raise ValueError("DEV_AUTH=1 запрещён при ENV=prod")
        if self.env == "prod" and self.jwt_secret is None:
            raise ValueError("JWT_SECRET обязателен при ENV=prod")
        if self.env == "prod" and self.bot_mode == "webhook" and self.max_webhook_secret is None:
            raise ValueError("MAX_WEBHOOK_SECRET обязателен при BOT_MODE=webhook и ENV=prod")
        return self

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def alembic_database_url(self) -> str:
        return self.migrate_database_url or self.database_url

    @property
    def webhook_url(self) -> str:
        return self.public_base_url.rstrip("/") + "/bot/webhook"


@lru_cache
def get_settings() -> Settings:
    return Settings()
