"""Живость и готовность (§11.2)."""

import asyncio

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.bot.subscriptions import config_problems, load_status
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_engine

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)

CHECK_TIMEOUT_S = 3.0


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _check_db() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await get_redis().ping()


async def _bot_status() -> dict[str, object]:
    """Справочно: состояние webhook бота. На код ответа не влияет (иначе откат деплоя)."""
    settings = get_settings()
    if settings.bot_mode != "webhook":
        return {"mode": settings.bot_mode}
    problems = config_problems(settings)
    state = "misconfigured" if problems else "unknown"
    checked_at = None
    try:
        status = await asyncio.wait_for(load_status(get_redis()), timeout=CHECK_TIMEOUT_S)
    except Exception:
        status = None
    if status is not None:
        state = status.get("state", state) if not problems else state
        problems = problems or list(status.get("problems") or [])
        checked_at = status.get("checked_at")
    return {"mode": "webhook", "state": state, "problems": problems, "checked_at": checked_at}


@router.get("/ready")
async def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    for name, check in (("db", _check_db), ("redis", _check_redis)):
        try:
            await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_S)
            checks[name] = "ok"
        except Exception as exc:
            log.warning("readiness_check_failed", check=name, error_type=type(exc).__name__)
            checks[name] = "fail"
    if all(v == "ok" for v in checks.values()):
        return JSONResponse({"status": "ok", "checks": checks, "bot": await _bot_status()})
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "not_ready",
                "message": "Сервис ещё не готов: недоступны зависимости",
                "details": {"checks": checks, "bot": await _bot_status()},
            }
        },
    )
