"""Пользователи: создание по данным MAX, профиль, согласия, удаление данных (FR-ONB)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.engagement import Notification, Subscription
from app.models.enums import AuditActor, ConsentDoc, NotificationStatus
from app.models.events import EventDraft, SavedSession
from app.models.geo import Locality
from app.models.users import Consent, User
from app.schemas.users import ConsentState, MeOut, MeUpdate
from app.services import audit

# Версии документов. Новая версия — повторный запрос согласия.
CONSENT_VERSIONS: dict[ConsentDoc, str] = {
    ConsentDoc.terms: "2026-09-23",
    ConsentDoc.privacy: "2026-09-23",
    ConsentDoc.org_pd: "2026-09-23",
}
REQUIRED_CONSENTS = (ConsentDoc.terms, ConsentDoc.privacy)

_MAX_PROFILE_FIELDS = ("first_name", "last_name", "username", "language_code")


def _snapshot(user: User, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: getattr(user, f) for f in fields}


def _clip(value: object, limit: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit]


async def get_by_max_id(session: AsyncSession, max_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    return result.scalar_one_or_none()


async def upsert_from_max(
    session: AsyncSession,
    max_user: dict[str, Any],
    *,
    dialog_chat_id: int | None = None,
    bot_started: bool = False,
) -> User:
    """Создаёт или обновляет пользователя по объекту user из initData или Update бота.

    initData: `id`, `first_name`, `last_name`, `username`, `language_code`;
    Bot API: `user_id`, `first_name`, `last_name`, `username`.
    """
    max_user_id = int(max_user.get("id") or max_user["user_id"])
    now = datetime.now(UTC)
    profile = {
        "first_name": _clip(max_user.get("first_name") or max_user.get("name"), 128),
        "last_name": _clip(max_user.get("last_name"), 128),
        "username": _clip(max_user.get("username"), 128),
        "language_code": _clip(max_user.get("language_code") or max_user.get("locale"), 16),
    }
    user = await get_by_max_id(session, max_user_id)
    if user is None:
        user = User(max_user_id=max_user_id, **profile, last_seen_at=now)
        if dialog_chat_id is not None:
            user.dialog_chat_id = dialog_chat_id
        if bot_started:
            user.bot_started_at = now
        session.add(user)
        await session.flush()
        await audit.record(
            session,
            action="user.create",
            entity_type="user",
            entity_id=user.id,
            actor_type=AuditActor.system,
            diff={"source": "bot" if dialog_chat_id is not None else "mini_app"},
        )
    else:
        tracked = (*_MAX_PROFILE_FIELDS, "dialog_chat_id")
        before = _snapshot(user, tracked)
        for key, value in profile.items():
            # Пустые значения из MAX не затирают сохранённые.
            if value is not None:
                setattr(user, key, value)
        if dialog_chat_id is not None:
            user.dialog_chat_id = dialog_chat_id
        if bot_started and user.bot_started_at is None:
            user.bot_started_at = now
        user.last_seen_at = now
        diff = audit.changes(before, _snapshot(user, tracked))
        if diff:
            await audit.record(
                session,
                action="user.sync_max_profile",
                entity_type="user",
                entity_id=user.id,
                actor_type=AuditActor.system,
                diff=diff,
            )
    await session.commit()
    return user


async def _accepted(session: AsyncSession, user_id: int) -> dict[tuple[str, str], datetime]:
    rows = await session.execute(
        select(Consent.doc, Consent.version, Consent.accepted_at).where(Consent.user_id == user_id)
    )
    return {(doc, version): accepted_at for doc, version, accepted_at in rows.all()}


async def consent_states(session: AsyncSession, user: User) -> list[ConsentState]:
    accepted = await _accepted(session, user.id)
    return [
        ConsentState(
            doc=doc,
            version=version,
            accepted=(doc.value, version) in accepted,
            accepted_at=accepted.get((doc.value, version)),
        )
        for doc, version in CONSENT_VERSIONS.items()
    ]


async def has_required_consents(session: AsyncSession, user: User) -> bool:
    accepted = await _accepted(session, user.id)
    return all((doc.value, CONSENT_VERSIONS[doc]) in accepted for doc in REQUIRED_CONSENTS)


async def accept_consents(session: AsyncSession, user: User, docs: list[ConsentDoc]) -> None:
    accepted = await _accepted(session, user.id)
    for doc in dict.fromkeys(docs):
        version = CONSENT_VERSIONS[doc]
        if (doc.value, version) in accepted:
            continue  # повторное принятие идемпотентно
        consent = Consent(user_id=user.id, doc=doc.value, version=version)
        session.add(consent)
        await session.flush()
        await audit.record(
            session,
            action="consent.accept",
            entity_type="consent",
            entity_id=consent.id,
            actor_user_id=user.id,
            diff={"doc": doc.value, "version": version},
        )
    await session.commit()


async def update_profile(session: AsyncSession, user: User, patch: MeUpdate) -> User:
    values = patch.model_dump(exclude_unset=True)
    # null для полей без NULL в БД — «не менять».
    for key in ("radius_km", "notify_digest", "notify_reminders", "interests"):
        if key in values and values[key] is None:
            values.pop(key)
    locality_id = values.get("locality_id")
    if locality_id is not None:
        exists = await session.scalar(select(Locality.id).where(Locality.id == locality_id))
        if exists is None:
            raise AppError(
                "locality_not_found",
                "Такой населённый пункт не найден",
                status_code=422,
                details={"locality_id": locality_id},
            )
    if "interests" in values:
        values["interests"] = list(dict.fromkeys(values["interests"]))
    before = _snapshot(user, tuple(values))
    for key, value in values.items():
        setattr(user, key, value)
    diff = audit.changes(before, values)
    if diff:
        await audit.record(
            session,
            action="user.update_profile",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            diff=diff,
        )
    await session.commit()
    return user


async def delete_user_data(session: AsyncSession, user: User) -> None:
    """FR-ONB-5: обезличивание профиля и удаление личных списков.

    Строка users остаётся (на неё ссылаются события и журнал), но без ПДн и без
    max_user_id — повторный вход создаст нового пользователя. Согласия сохраняются
    как подтверждение факта согласия.
    """
    user_id = user.id
    await session.execute(delete(SavedSession).where(SavedSession.user_id == user_id))
    await session.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await session.execute(delete(EventDraft).where(EventDraft.user_id == user_id))
    await session.execute(
        delete(Notification).where(
            Notification.user_id == user_id,
            Notification.status == NotificationStatus.scheduled,
        )
    )
    user.max_user_id = None
    user.dialog_chat_id = None
    user.first_name = None
    user.last_name = None
    user.username = None
    user.language_code = None
    user.locality_id = None
    user.home_point = None
    user.interests = []
    user.birth_year = None
    user.notify_digest = False
    user.notify_reminders = False
    user.deleted_at = datetime.now(UTC)
    await audit.record(
        session,
        action="user.delete_data",
        entity_type="user",
        entity_id=user_id,
        actor_user_id=user_id,
    )
    await session.commit()


def is_admin(user: User, settings: Settings, review_role: str | None = None) -> bool:
    if review_role is not None:
        return review_role == "admin"
    return user.max_user_id is not None and user.max_user_id in settings.admin_max_user_ids


async def to_me_out(
    session: AsyncSession, user: User, settings: Settings, review_role: str | None = None
) -> MeOut:
    consents = await consent_states(session, user)
    required_ok = all(c.accepted for c in consents if c.doc in REQUIRED_CONSENTS)
    has_place = user.locality_id is not None or user.home_point is not None
    return MeOut(
        id=user.id,
        max_user_id=user.max_user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        locality_id=user.locality_id,
        has_home_point=user.home_point is not None,
        radius_km=user.radius_km,
        interests=list(user.interests or []),
        birth_year=user.birth_year,
        notify_digest=user.notify_digest,
        notify_reminders=user.notify_reminders,
        consents=consents,
        needs_onboarding=not (required_ok and has_place),
        is_admin=is_admin(user, settings, review_role),
    )
