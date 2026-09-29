"""Настройки arq-воркера: обновления бота, модерация, проверки верификации, сообщения."""

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import structlog
from arq import Retry
from arq.connections import RedisSettings
from arq.cron import cron
from redis.asyncio import Redis
from sqlalchemy import select

from app.bot import keyboards, texts
from app.bot import notify as bot_notify
from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import RedisStateStore
from app.bot.notify import BotNotifier
from app.bot.subscriptions import check_webhook, sync_commands
from app.core.config import get_settings
from app.core.jobs import ArqJobQueue
from app.core.logging import configure_logging
from app.db.session import make_engine, make_sessionmaker
from app.integrations.max import client_from_settings
from app.models.events import Event, EventSession, SavedSession
from app.models.orgs import Organization
from app.models.users import User
from app.services import moderation as moderation_service
from app.services import notifications as notifications_service
from app.services import verification as verification_service
from app.services.notify import QueuedNotifier

_settings = get_settings()
configure_logging(_settings.log_level)
log = structlog.get_logger(__name__)

# Сообщение в бот: до SEND_TRIES попыток с растущей паузой (MAX недоступен, 429, 5xx).
SEND_TRIES = 5
SEND_BACKOFF_S = 15


# Для `arq --custom-log-dict`: не даём arq ставить свой текстовый handler, пишем через root (JSON).
ARQ_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"arq": {"handlers": [], "propagate": True}},
}


async def ping(_ctx: dict[str, Any]) -> str:
    return "pong"


async def process_bot_update(ctx: dict[str, Any], update: dict[str, Any]) -> None:
    """Имя задачи совпадает с app.bot.queue.PROCESS_UPDATE_JOB."""
    bot: BotContext | None = ctx.get("bot")
    if bot is None:
        log.warning("bot_update_dropped", reason="MAX_BOT_TOKEN не задан")
        return
    await handle_update(bot, update)


async def ensure_bot_webhook(ctx: dict[str, Any]) -> str | None:
    """Cron: подписка на webhook могла пропасть (снял poller, сброс в MAX) — восстанавливаем."""
    if _settings.bot_mode != "webhook":
        return None
    return await check_webhook(_settings, ctx["app_redis"], force=False)


async def moderate_event(ctx: dict[str, Any], event_id: int, _attempt: int = 0) -> str | None:
    """`_attempt` — для задач, поставленных прежними версиями в очередь; не используется.

    Если правила не пропустили событие, сервис ставит alert_moderators в очередь.
    """
    async with ctx["db"]() as session:
        return await moderation_service.moderate_event(session, event_id, notifier=_notifier(ctx))


def _retry(
    ctx: dict[str, Any], event: str, exc: BaseException | None = None, **fields: Any
) -> None:
    """Повтор задачи с растущей паузой, после SEND_TRIES — только лог (без ПДн)."""
    attempt = int(ctx.get("job_try") or 1)
    if attempt >= SEND_TRIES:
        log.error(f"{event}_failed", attempts=attempt, **fields)
        return
    log.warning(f"{event}_retry", attempt=attempt, **fields)
    raise Retry(defer=SEND_BACKOFF_S * attempt) from exc


async def alert_moderators(ctx: dict[str, Any], kind: str, entity_id: int) -> int:
    """Заявка на модерацию → сообщения модераторам; недоставленным — повтор."""
    bot: BotContext | None = ctx.get("bot")
    if bot is None:
        log.warning("moderators_alert_dropped", reason="MAX_BOT_TOKEN не задан")
        return 0
    failed = await bot_notify.alert_moderators(
        bot.db, bot.max, bot.settings, bot.redis, kind, entity_id
    )
    if failed:
        _retry(ctx, "moderators_alert", kind=kind, entity_id=entity_id, failed=len(failed))
    return len(failed)


async def close_moderation(ctx: dict[str, Any], kind: str, entity_id: int) -> int:
    """Решение по заявке → вердикт в сообщениях модераторов, кнопки убраны."""
    bot: BotContext | None = ctx.get("bot")
    if bot is None:
        return 0
    failed = await bot_notify.close_moderation(
        bot.db, bot.max, bot.settings, bot.redis, kind, entity_id
    )
    if failed:
        _retry(ctx, "moderation_close", kind=kind, entity_id=entity_id, failed=failed)
    return failed


async def check_verification(ctx: dict[str, Any], request_id: int) -> str | None:
    async with ctx["db"]() as session:
        request = await verification_service.run_checks(
            session,
            request_id,
            notifier=_notifier(ctx),
        )
    return request.status if request is not None else None


async def send_user_message(
    ctx: dict[str, Any], user_id: int, text: str, deeplink: str | None = None
) -> None:
    """Сообщение из очереди (QueuedNotifier). Гостям не уходит (BotNotifier их пропускает)."""
    notifier: BotNotifier | None = ctx.get("notifier")
    if notifier is None:
        log.warning("user_message_dropped", reason="MAX_BOT_TOKEN не задан")
        return
    try:
        await notifier.send(user_id, text, deeplink)
    except Exception as exc:
        _retry(ctx, "user_message", exc, user_id=user_id, error=type(exc).__name__)


async def request_phone(ctx: dict[str, Any], user_id: int, org_id: int) -> None:
    """Кнопка «Подтвердить телефон» после заявки на проверку способом Б."""
    notifier: BotNotifier | None = ctx.get("notifier")
    if notifier is None:
        log.warning("phone_request_dropped", reason="MAX_BOT_TOKEN не задан")
        return
    async with ctx["db"]() as session:
        org = await session.get(Organization, org_id)
    if org is None:
        return
    await notifier.send_raw(
        user_id, texts.PHONE_REQUEST.format(org=org.name), keyboards.phone_request()
    )


async def schedule_reminders(ctx: dict[str, Any]) -> str:
    """Создаёт дедуплицированные уведомления за 24 и 2 часа до сохранённых сеансов."""
    now = datetime.now(UTC)
    async with ctx["db"]() as session:
        rows = await session.execute(
            select(SavedSession.user_id, EventSession, Event)
            .join(EventSession, EventSession.id == SavedSession.session_id)
            .join(Event, Event.id == EventSession.event_id)
            .where(EventSession.starts_at > now, Event.status == "published")
        )
        count = 0
        for user_id, event_session, event in rows:
            user = await session.get(User, user_id)
            if user is None or not user.notify_reminders or user.bot_started_at is None:
                continue
            for hours in (24, 2):
                item = await notifications_service.schedule(
                    session,
                    user,
                    kind="reminder",
                    payload={
                        "event_id": event.id,
                        "session_id": event_session.id,
                        "title": event.title,
                        "hours": hours,
                    },
                    dedup_key=f"reminder:{user.id}:{event_session.id}:{hours}",
                    scheduled_at=event_session.starts_at - timedelta(hours=hours),
                )
                count += bool(item)
        await session.commit()
    return str(count)


async def deliver_notifications(ctx: dict[str, Any]) -> str:
    notifier = _notifier(ctx)
    async with ctx["db"]() as session:
        items = await notifications_service.due(session)
        sent = 0
        for item in items:
            user = await session.get(User, item.user_id)
            if user is None or user.bot_started_at is None:
                item.status = "skipped"
                continue
            try:
                title = item.payload.get("title", "событие")
                hours = item.payload.get("hours")
                text = (
                    f"Событие «{title}» отменено."
                    if item.kind == "cancelled"
                    else "Дайджест на выходные уже в приложении 📍"
                    if item.kind == "digest"
                    else f"Напоминание: «{title}»"
                )
                if hours:
                    text += f" через {hours} ч."
                deeplink = (
                    f"ev_{item.payload['event_id']}"
                    if item.payload.get("event_id")
                    else "feed_weekend"
                )
                await notifier.send(user.id, text, deeplink)
                item.status, item.sent_at = "sent", datetime.now(UTC)
                sent += 1
            except Exception as exc:
                item.attempts += 1
                item.error = type(exc).__name__
                if item.attempts >= 5:
                    item.status = "failed"
        await session.commit()
    return str(sent)


async def schedule_digest(ctx: dict[str, Any]) -> str:
    """Четверговый дайджест: единая запись на пользователя, события подбираются аппом."""
    now = datetime.now(UTC)
    async with ctx["db"]() as session:
        users = await session.scalars(
            select(User).where(User.notify_digest.is_(True), User.bot_started_at.is_not(None))
        )
        count = 0
        for user in users:
            item = await notifications_service.schedule(
                session,
                user,
                kind="digest",
                payload={"preset": "weekend"},
                dedup_key=f"digest:{user.id}:{now.date().isoformat()}",
                scheduled_at=now,
            )
            count += bool(item)
        await session.commit()
    return str(count)


def _notifier(ctx: dict[str, Any]) -> Any:
    notifier = ctx.get("notifier")
    if notifier is None:
        # Без токена бота сообщения некуда доставить: результат всё равно виден в приложении.
        return _NullNotifier()
    return notifier


class _NullNotifier:
    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        log.info("user_message_skipped", user_id=user_id)

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        log.info("moderators_alert_skipped", kind=kind, entity_id=entity_id)

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        return None


async def startup(ctx: dict[str, Any]) -> None:
    engine = make_engine(_settings.database_url)
    ctx["engine"] = engine
    redis = Redis.from_url(_settings.redis_url)
    ctx["app_redis"] = redis
    db = make_sessionmaker(engine)
    ctx["db"] = db
    ctx["jobs"] = ArqJobQueue(_settings.redis_url)
    client = client_from_settings(_settings)
    if client is not None:
        # Воркер доставляет сам; бот ставит сообщения другим в очередь — с повторами.
        ctx["notifier"] = BotNotifier(db, client, _settings.max_bot_username, ctx["jobs"])
        ctx["bot"] = BotContext(
            settings=_settings,
            db=db,
            max=client,
            states=RedisStateStore(redis),
            redis=redis,
            notifier=QueuedNotifier(ctx["jobs"]),
            jobs=ctx["jobs"],
        )
        await sync_commands(client)


async def shutdown(ctx: dict[str, Any]) -> None:
    bot: BotContext | None = ctx.get("bot")
    if bot is not None:
        await bot.max.aclose()
    await ctx["jobs"].close()
    await ctx["app_redis"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        process_bot_update,
        moderate_event,
        check_verification,
        send_user_message,
        alert_moderators,
        close_moderation,
        request_phone,
        schedule_reminders,
        deliver_notifications,
        schedule_digest,
        ensure_bot_webhook,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    health_check_interval = 30
    cron_jobs: ClassVar[list[Any]] = [
        cron(schedule_reminders, minute={0, 15, 30, 45}),
        cron(deliver_notifications, minute=set(range(60))),
        cron(schedule_digest, weekday={3}, hour={18}, minute={0}),
        cron(ensure_bot_webhook, minute=set(range(2, 60, 5))),
    ]
