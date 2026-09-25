"""Очередь уведомлений: дедупликация, тихие часы и доставка с backoff."""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Notification
from app.models.users import User


def _quiet_end(now: datetime, tz_name: str = "Europe/Moscow") -> datetime:
    local = now.astimezone(ZoneInfo(tz_name))
    if local.hour < 9:
        end = local.replace(hour=9, minute=0, second=0, microsecond=0)
    elif local.hour >= 22:
        end = (local + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        return now
    return end.astimezone(UTC)


async def schedule(
    session: AsyncSession,
    user: User,
    *,
    kind: str,
    payload: dict[str, Any],
    dedup_key: str,
    scheduled_at: datetime,
    timezone: str = "Europe/Moscow",
) -> Notification | None:
    when = max(scheduled_at, _quiet_end(scheduled_at, timezone))
    row = await session.scalar(
        insert(Notification)
        .values(
            user_id=user.id,
            kind=kind,
            payload=payload,
            dedup_key=dedup_key,
            scheduled_at=when,
            status="scheduled",
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Notification.id)
    )
    if row is None:
        return None
    await session.flush()
    return await session.get(Notification, row)


async def due(session: AsyncSession, limit: int = 100) -> list[Notification]:
    return list(
        await session.scalars(
            select(Notification)
            .where(
                Notification.status == "scheduled", Notification.scheduled_at <= datetime.now(UTC)
            )
            .order_by(Notification.scheduled_at, Notification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
