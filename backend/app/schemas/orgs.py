from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import OrgKind, OrgRole

Inn = Annotated[str, StringConstraints(pattern=r"^(\d{10}|\d{12})$")]
HttpsUrl = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=2048, pattern=r"^https://\S+$")
]
Text255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]


class OrgCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Text255
    kind: OrgKind
    inn: Inn | None = None
    locality_id: int | None = None
    address: str | None = Field(default=None, max_length=500)
    website: HttpsUrl | None = None
    vk_url: HttpsUrl | None = None
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class OrgUpdate(BaseModel):
    """Меняются только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    name: Text255 | None = None
    kind: OrgKind | None = None
    inn: Inn | None = None
    locality_id: int | None = None
    address: str | None = Field(default=None, max_length=500)
    website: HttpsUrl | None = None
    vk_url: HttpsUrl | None = None
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class OrgOut(BaseModel):
    id: int
    name: str
    kind: str
    inn: str | None
    ogrn: str | None
    registry_name: str | None
    locality_id: int | None
    locality_name: str | None = None
    address: str | None
    website: str | None
    vk_url: str | None
    description: str | None
    # Контакты видны только участникам организации.
    phone: str | None = None
    email: str | None = None
    verified: bool
    verification_status: str
    verification_method: str | None
    verified_at: datetime | None
    my_role: OrgRole | None = Field(default=None, description="Роль текущего пользователя")


class RegistryLookupOut(BaseModel):
    """Автозаполнение формы организации из ЕГРЮЛ/ЕГРИП (DaData)."""

    found: bool
    inn: str
    ogrn: str | None = None
    name: str | None = None
    status: str | None = None
    address: str | None = None
    region: str | None = None
    kind: Literal["legal", "individual"] | None = None


class MemberOut(BaseModel):
    user_id: int
    name: str
    role: OrgRole
    joined_at: datetime
    is_me: bool


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: OrgRole = OrgRole.editor
    grants_verification: bool = Field(
        default=False, description="Способ A: принятие верифицирует организацию (только админ)"
    )


class InviteOut(BaseModel):
    token: str = Field(description="Показывается один раз; в БД хранится только хеш")
    payload: str = Field(description="startapp-payload inv_<token>")
    url: str | None = Field(description="Диплинк https://max.ru/<бот>?startapp=inv_<token>")
    role: OrgRole
    grants_verification: bool
    expires_at: datetime


class InvitePreview(BaseModel):
    org_id: int
    org_name: str
    role: OrgRole
    grants_verification: bool
    expires_at: datetime
    valid: bool
    reason: str | None = None


class InviteAccepted(BaseModel):
    org_id: int
    role: OrgRole
    verified: bool


class VerificationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["registry_auto", "manual"] = "registry_auto"
    inn: Inn | None = Field(default=None, description="По умолчанию — ИНН организации")
    site_url: HttpsUrl | None = Field(
        default=None, description="Официальный сайт или страница ВК с кодом AFISHA-XXXXXX"
    )
    comment: str | None = Field(default=None, max_length=1000)


StepStatus = Literal["ok", "failed", "pending", "skipped"]


class VerificationStep(BaseModel):
    code: Literal["registry", "phone", "site_code", "page_check", "admin"]
    title: str
    status: StepStatus
    message: str | None = None


class VerificationOut(BaseModel):
    id: int
    org_id: int
    method: str
    status: str
    code: str | None = Field(description="Разместить на странице организации")
    site_url: str | None
    steps: list[VerificationStep]
    decision_reason: str | None
    created_at: datetime
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None = Field(description="Раньше этого повтор недоступен")
