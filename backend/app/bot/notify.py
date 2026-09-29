"""Доставка сообщений пользователю в личный диалог с ботом (для воркера и бота)."""

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, render, texts
from app.core.config import Settings
from app.core.jobs import JobQueue
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.events import Event, EventSession
from app.models.geo import Locality, Venue
from app.models.orgs import Organization, VerificationRequest
from app.models.users import User
from app.services.localities import DEFAULT_TIMEZONE
from app.services.notify import QueuedNotifier

log = structlog.get_logger(__name__)


class BotNotifier:
    def __init__(
        self,
        db: SessionMaker,
        client: MaxClient,
        web_app: str | None,
        jobs: JobQueue | None = None,
    ) -> None:
        self._db = db
        self._client = client
        self._web_app = web_app
        # Модераторам — только через очередь (с повторами), см. alert_moderators ниже.
        self._jobs = jobs

    async def _recipient(self, user_id: int) -> tuple[int | None, int | None] | None:
        """(chat_id, max_user_id) — диалог, если известен, иначе пользователь MAX."""
        async with self._db() as session:
            user = await session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            return None
        if user.max_user_id is None:
            # Гость сайта (/auth/guest): диалога с ботом у него нет — в бот не пишем.
            log.info("notify_guest_skipped", user_id=user_id)
            return None
        if user.dialog_chat_id is not None:
            return user.dialog_chat_id, None
        if user.max_user_id is not None:
            return None, user.max_user_id
        return None

    async def send_raw(
        self, user_id: int, text: str, keyboard: dict[str, Any] | None = None
    ) -> bool:
        recipient = await self._recipient(user_id)
        if recipient is None:
            log.info("notify_no_recipient", user_id=user_id)
            return False
        chat_id, max_user_id = recipient
        await self._client.send_message(
            chat_id=chat_id,
            user_id=max_user_id,
            text=text,
            attachments=[keyboard] if keyboard else None,
        )
        return True

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        keyboard = (
            keyboards.open_link(self._web_app, deeplink) if deeplink and self._web_app else None
        )
        await self.send_raw(user_id, text, keyboard)

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        if self._jobs is None:
            log.warning("moderators_alert_no_queue", kind=kind, entity_id=entity_id)
            return
        await QueuedNotifier(self._jobs).alert_moderators(kind, entity_id)

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        if self._jobs is not None:
            await QueuedNotifier(self._jobs).moderation_closed(kind, entity_id)


# --- Модерация: уведомления админам ---------------------------------------------------------

# Кому и какое сообщение ушло (id модератора → mid), чтобы после решения убрать у всех кнопки.
MODERATION_MSGS_TTL_S = 30 * 24 * 3600


def moderation_key(kind: str, entity_id: int) -> str:
    return f"mod:msgs:{kind}:{entity_id}"


@dataclass(frozen=True)
class ModerationCard:
    text: str
    status: str
    # Диплинк мини-приложения на карточку модератора (из бота на сайт не ведём).
    payload: str


def _name(user: User | None) -> str:
    if user is None:
        return texts.MOD_NONE
    return " ".join(p for p in (user.first_name, user.last_name) if p) or texts.MOD_NONE


async def _event_card(session: AsyncSession, event_id: int) -> ModerationCard | None:
    event = await session.get(Event, event_id)
    if event is None:
        return None
    starts_at = await session.scalar(
        select(EventSession.starts_at)
        .where(EventSession.event_id == event_id)
        .order_by(EventSession.starts_at)
        .limit(1)
    )
    venue = await session.get(Venue, event.venue_id) if event.venue_id else None
    locality_id = event.locality_id or (venue.locality_id if venue else None)
    locality = await session.get(Locality, locality_id) if locality_id else None
    org = await session.get(Organization, event.organization_id) if event.organization_id else None
    author = await session.get(User, event.author_user_id) if event.author_user_id else None
    # Время — в часовом поясе населённого пункта события.
    tz = locality.timezone if locality and locality.timezone else DEFAULT_TIMEZONE
    if venue is not None:
        place = ", ".join(p for p in (venue.name, venue.address) if p)
    else:
        place = texts.MOD_ONLINE if event.is_online else texts.MOD_NONE
    text = texts.MOD_EVENT.format(
        id=event.id,
        title=event.title,
        when=render.when(starts_at, tz) if starts_at else texts.MOD_NONE,
        venue=place,
        locality=locality.name if locality else texts.MOD_NONE,
        organizer=org.name if org else _name(author),
        reasons=event.moderation_reason or texts.MOD_NONE,
    )
    return ModerationCard(text, str(event.status), f"mod_{event.id}")


async def _org_card(session: AsyncSession, request_id: int) -> ModerationCard | None:
    request = await session.get(VerificationRequest, request_id)
    if request is None:
        return None
    org = await session.get(Organization, request.org_id)
    if org is None:
        return None
    locality = await session.get(Locality, org.locality_id) if org.locality_id else None
    submitter = await session.get(User, request.submitted_by)
    contacts = ", ".join(c for c in (org.phone, org.email, org.website, org.vk_url) if c)
    text = texts.MOD_ORG.format(
        id=request.id,
        name=org.name,
        kind=org.kind,
        inn=request.inn or org.inn or texts.MOD_NONE,
        locality=locality.name if locality else texts.MOD_NONE,
        contacts=contacts or texts.MOD_NONE,
        method=texts.MOD_METHODS.get(request.method, request.method),
        submitter=_name(submitter),
    )
    return ModerationCard(text, str(request.status), "mod_0")


async def moderation_card(db: SessionMaker, kind: str, entity_id: int) -> ModerationCard | None:
    """kind: e — событие, v — заявка организации на проверку."""
    async with db() as session:
        if kind == "e":
            return await _event_card(session, entity_id)
        return await _org_card(session, entity_id)


def _decode(data: dict[Any, Any]) -> dict[str, str]:
    return {
        (k.decode() if isinstance(k, bytes) else str(k)): (
            v.decode() if isinstance(v, bytes) else str(v)
        )
        for k, v in data.items()
    }


async def alert_moderators(
    db: SessionMaker, client: MaxClient, settings: Settings, redis: Any, kind: str, entity_id: int
) -> list[int]:
    """Заявка → каждому из ADMIN_MAX_USER_IDS сообщение с «Одобрить» / «Отклонить».

    Возвращает модераторов, до которых не дошло (для повтора задачи). Кому уже отправлено —
    записано в Redis, повтор им не дублирует. Ошибка одному не мешает остальным.
    """
    admins = sorted(set(settings.admin_max_user_ids))
    if not admins:
        log.warning("moderators_not_configured", kind=kind, entity_id=entity_id)
        return []
    card = await moderation_card(db, kind, entity_id)
    if card is None or card.status != "pending":
        return []
    key = moderation_key(kind, entity_id)
    sent = _decode(await redis.hgetall(key))
    keyboard = keyboards.moderation_alert(kind, entity_id, settings.max_bot_username, card.payload)
    failed: list[int] = []
    for admin_id in admins:
        if str(admin_id) in sent:
            continue
        try:
            result = await client.send_message(
                user_id=admin_id, text=card.text, attachments=[keyboard]
            )
        except Exception as exc:
            # Без id модератора и текста заявки: только тип ошибки.
            log.warning(
                "moderator_alert_failed", kind=kind, entity_id=entity_id, error=type(exc).__name__
            )
            failed.append(admin_id)
            continue
        # SendMessageResult.message.body.mid — нужен для editMessage после решения.
        mid = (((result or {}).get("message") or {}).get("body") or {}).get("mid")
        if mid:
            await redis.hset(key, str(admin_id), str(mid))
            await redis.expire(key, MODERATION_MSGS_TTL_S)
    log.info(
        "moderators_alerted",
        kind=kind,
        entity_id=entity_id,
        admins=len(admins),
        failed=len(failed),
    )
    return failed


async def close_moderation(
    db: SessionMaker, client: MaxClient, settings: Settings, redis: Any, kind: str, entity_id: int
) -> int:
    """Решение принято: в сообщениях всех модераторов — вердикт, кнопки убраны (editMessage).

    Возвращает число сообщений, которые не удалось поправить.
    """
    card = await moderation_card(db, kind, entity_id)
    if card is None:
        # Администратор удалил событие: карточки нет, закрываем сообщения вердиктом «удалено».
        card = ModerationCard(texts.MOD_DELETED_CARD.format(id=entity_id), "deleted", "")
    if card.status == "pending":
        return 0
    key = moderation_key(kind, entity_id)
    mids = _decode(await redis.hgetall(key))
    if not mids:
        return 0
    verdict = texts.MOD_VERDICTS.get(card.status, card.status)
    keyboard = keyboards.moderation_closed(settings.max_bot_username, card.payload)
    failed = 0
    for mid in mids.values():
        try:
            await client.edit_message(
                mid,
                text=card.text + texts.MOD_CLOSED.format(verdict=verdict),
                attachments=[keyboard] if keyboard else [],
            )
        except Exception as exc:
            failed += 1
            log.warning(
                "moderation_close_failed", kind=kind, entity_id=entity_id, error=type(exc).__name__
            )
    if not failed:
        await redis.delete(key)
    log.info("moderation_closed", kind=kind, entity_id=entity_id, edited=len(mids) - failed)
    return failed
