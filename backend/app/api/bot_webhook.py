"""Webhook бота MAX (§9.2): проверка секрета, быстрый 200, обработка в очереди."""

import hmac
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, HTTPException, Request

from app.api.deps import SettingsDep
from app.bot.queue import UpdateSink

router = APIRouter(tags=["bot"])
log = structlog.get_logger(__name__)


@router.post("/bot/webhook", summary="Обновления бота от MAX", include_in_schema=False)
async def bot_webhook(
    request: Request,
    settings: SettingsDep,
    secret: Annotated[str | None, Header(alias="X-Max-Bot-Api-Secret")] = None,
) -> dict[str, bool]:
    # Секрет проверяется до разбора тела: чужой запрос получает 401, а не 422.
    expected = settings.max_webhook_secret
    if (
        expected is None
        or secret is None
        or not hmac.compare_digest(secret.encode(), expected.get_secret_value().encode())
    ):
        log.warning("bot_webhook_bad_secret", has_secret=secret is not None)
        raise HTTPException(401, detail="Неверный секрет webhook")
    try:
        update = await request.json()
    except ValueError as exc:
        raise HTTPException(400, detail="Тело запроса — не JSON") from exc
    if not isinstance(update, dict) or "update_type" not in update:
        raise HTTPException(400, detail="Ожидался объект Update")
    sink: UpdateSink = request.app.state.update_sink
    await sink.put(update)
    return {"ok": True}
