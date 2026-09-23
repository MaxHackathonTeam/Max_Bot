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
    database_url: str = "postgresql+asyncpg://afisha:afisha@db:5432/afisha"
    redis_url: str = "redis://redis:6379/0"

    # Доступ
    jwt_secret: SecretStr | None = None
    admin_max_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # GigaChat
    gigachat_auth_key: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_oauth_url: str = ""
    gigachat_api_url: str = ""
    gigachat_model: str = "GigaChat"
    llm_daily_token_budget: int = 200_000

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
        return self

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
