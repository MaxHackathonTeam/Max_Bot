from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.engagement import AnalyticsEvent
from app.models.events import Event
from app.models.orgs import OrgMember


async def record(
    session: AsyncSession,
    name: str,
    *,
    user_id: int | None = None,
    props: dict[str, Any] | None = None,
) -> None:
    session.add(AnalyticsEvent(user_id=user_id, name=name, props=props or {}))


async def organization_stats(session: AsyncSession, user: Any, org_id: int) -> dict[str, Any]:
    member = await session.scalar(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user.id)
    )
    if member is None:
        raise AppError("forbidden", "Нет доступа к статистике организации", 403)
    since = datetime.now(UTC) - timedelta(days=30)
    rows = await session.execute(
        select(AnalyticsEvent.name, func.count())
        .where(
            AnalyticsEvent.created_at >= since, AnalyticsEvent.props["org_id"].astext == str(org_id)
        )
        .group_by(AnalyticsEvent.name)
    )
    counts = {name: int(count) for name, count in rows}
    event_count = await session.scalar(
        select(func.count()).select_from(Event).where(Event.organization_id == org_id)
    )
    return {
        "org_id": org_id,
        "period_days": 30,
        "events": int(event_count or 0),
        "views": counts.get("event_view", 0),
        "saves": counts.get("event_save", 0),
        "shares": counts.get("event_share", 0),
    }
