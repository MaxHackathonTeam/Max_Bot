from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import ConsentDoc

InterestSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,32}$")]


class ConsentState(BaseModel):
    doc: ConsentDoc
    version: str = Field(description="Текущая версия документа")
    accepted: bool = Field(description="Принята ли текущая версия")
    accepted_at: datetime | None = None


class MeOut(BaseModel):
    id: int
    max_user_id: int | None
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    locality_id: int | None
    has_home_point: bool
    radius_km: int
    interests: list[str]
    birth_year: int | None
    notify_digest: bool
    notify_reminders: bool
    consents: list[ConsentState]
    needs_onboarding: bool = Field(
        description="Нет согласия с документами или не выбран населённый пункт"
    )
    is_admin: bool


class MeUpdate(BaseModel):
    """Меняются только переданные поля; null для locality_id/birth_year — сброс."""

    model_config = ConfigDict(extra="forbid")

    locality_id: int | None = None
    radius_km: Literal[5, 15, 30, 50] | None = None
    interests: list[InterestSlug] | None = Field(default=None, max_length=20)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    notify_digest: bool | None = None
    notify_reminders: bool | None = None


class ConsentsIn(BaseModel):
    docs: list[ConsentDoc] = Field(min_length=1, max_length=3)


class AuthMaxIn(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class ReviewLoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — тип токена OAuth, не пароль
    expires_at: datetime
    user: MeOut
    start_param: str | None = Field(default=None, description="Параметр диплинка startapp")
