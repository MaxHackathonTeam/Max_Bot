"""Черновик из сообщения: LLM извлекает поля, автор проверяет их в обычной форме."""

import asyncio
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.llm.runner import LlmRunner
from app.llm.schemas import DraftFieldsOut
from app.models.enums import AuditActor, PriceType
from app.models.events import Event
from app.models.users import User
from app.schemas.manage import EventCreate, SessionIn
from app.services import audit, event_editor
from app.services.categories import BY_SLUG


async def create_from_text(
    session: AsyncSession,
    user: User,
    text: str,
    org_id: int | None,
    llm: LlmRunner | None,
) -> Event:
    source = text.strip()
    if not 10 <= len(source) <= 4000:
        raise AppError("bad_text", "Текст анонса должен содержать от 10 до 4000 символов")
    extracted: DraftFieldsOut | None = None
    if llm is not None:
        try:
            result = await asyncio.wait_for(
                llm.run_json(
                    "draft_extract",
                    "draft_extract",
                    DraftFieldsOut,
                    text=source,
                    categories=", ".join(BY_SLUG),
                ),
                timeout=12,
            )
            extracted = result.value
        except (TimeoutError, OSError):
            pass
    fields: dict[str, object] = {
        "title": source.splitlines()[0][:120],
        "description": source,
        "organization_id": org_id,
    }
    ai_fields: list[str] = []
    if extracted:
        for key in ("title", "description", "category", "price_type", "price_min", "ticket_url"):
            value = getattr(extracted, key)
            if value is None or (key == "category" and value not in BY_SLUG):
                continue
            if key == "ticket_url" and (
                urlparse(value).scheme != "https" or not urlparse(value).hostname
            ):
                continue
            fields[key] = value
            ai_fields.append(key)
        if extracted.starts_at:
            try:
                start = datetime.fromisoformat(extracted.starts_at)
                if start.tzinfo and start > datetime.now(start.tzinfo):
                    fields["sessions"] = [SessionIn(starts_at=start)]
                    ai_fields.append("sessions")
            except ValueError:
                pass
    fields["price_type"] = fields.get("price_type", PriceType.unknown)
    event = await event_editor.create(session, user, EventCreate.model_validate(fields))
    if ai_fields:
        event.ai_fields = ai_fields
        await audit.record(
            session,
            action="event.ai_fields",
            entity_type="event",
            entity_id=event.id,
            actor_type=AuditActor.llm,
            diff={"fields": ai_fields},
        )
        await session.commit()
    return event
