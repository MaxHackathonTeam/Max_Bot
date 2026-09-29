"""Диагностика «бот молчит» по всей цепочке MAX → Caddy → /bot/webhook → очередь → воркер → MAX.

Проверяет: конфигурацию, TLS и связь с MAX API (GET /me), подписку (GET /subscriptions),
что /bot/webhook доступен снаружи (без секрета ждём 401), что воркер жив (health-check arq)
и разбирает очередь, статус последней проверки подписки.

На сервере:
    docker compose -f compose.yaml -f compose.prod.yaml exec api python -m app.bot.doctor
    ... python -m app.bot.doctor --fix   # пересоздать подписку с текущим секретом

Вывод без токена, секрета и ПДн: только имя/username бота, URL подписок и типы обновлений.
Код выхода 0 — всё в порядке, 1 — есть проблемы.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

import httpx
from arq.constants import default_queue_name, health_check_key_suffix
from redis.asyncio import Redis

from app.bot.poller import HEARTBEAT_KEY
from app.bot.subscriptions import check_webhook, config_problems, load_status, sync_commands
from app.core.config import Settings, get_settings
from app.integrations.max import MaxClient
from app.integrations.max.client import UPDATE_TYPES, describe_error

WORKER_HEALTH_KEY = default_queue_name + health_check_key_suffix
# Столько задач в очереди без живого воркера — точно «webhook принимает, ответа нет».
QUEUE_BACKLOG = 20


def _ts(value: Any) -> str:
    if not isinstance(value, int | float):
        return "—"
    # MAX отдаёт time подписки в миллисекундах, наш статус — в секундах.
    seconds = value / 1000 if value > 10**11 else value
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _subscription_problems(settings: Settings, subs: list[dict[str, Any]]) -> list[str]:
    urls = [s.get("url") for s in subs]
    if settings.bot_mode != "webhook":
        return (
            ["BOT_MODE=polling, но есть webhook-подписка — GET /updates не работает"]
            if subs
            else []
        )
    problems: list[str] = []
    if settings.webhook_url not in urls:
        problems.append("Нет подписки на ожидаемый URL — MAX не присылает обновления")
    for s in subs:
        types = s.get("update_types")
        if s.get("url") == settings.webhook_url and types is not None:
            missing = set(UPDATE_TYPES) - set(types)
            if missing:
                problems.append(f"Подписка без типов: {', '.join(sorted(missing))}")
    if any(u != settings.webhook_url for u in urls):
        problems.append("Есть подписки на другие URL — обновления уходят и туда")
    return problems


async def _poller_problems(redis: Redis) -> list[str]:
    try:
        beat = await redis.get(HEARTBEAT_KEY)
    except Exception as exc:
        return [f"Redis недоступен ({type(exc).__name__}) — не проверить, жив ли bot-poller"]
    if beat is None:
        return [
            "bot-poller не опрашивает MAX (нет heartbeat) — локально запускай `make up` "
            "(профиль compose `local`) и смотри `docker compose logs bot-poller`"
        ]
    print(f"bot-poller: последний опрос {_ts(int(beat))}")
    return []


async def _worker_problems(redis: Redis) -> list[str]:
    """Воркер arq раз в health_check_interval пишет ключ с TTL: нет ключа — воркер не работает."""
    try:
        health = await redis.get(WORKER_HEALTH_KEY)
        queued = int(await redis.zcard(default_queue_name))
    except Exception as exc:
        return [f"Redis недоступен ({type(exc).__name__}) — не проверить воркер и очередь"]
    if isinstance(health, bytes):
        health = health.decode()
    print(f"Воркер: {health or 'нет health-check'}; в очереди задач: {queued}")
    problems: list[str] = []
    if health is None:
        problems.append(
            "Воркер не отмечается в Redis — обновления из webhook копятся в очереди без ответа "
            "(docker compose ... ps worker, logs worker)"
        )
    elif queued >= QUEUE_BACKLOG:
        problems.append(f"В очереди {queued} задач — воркер не успевает или завис")
    return problems


async def _external_problems(settings: Settings) -> list[str]:
    """POST на публичный URL webhook без секрета: 401 — Caddy и API на месте."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(settings.webhook_url, json={})
    except Exception as exc:
        return [f"{settings.webhook_url} недоступен снаружи ({type(exc).__name__}): DNS/TLS/Caddy"]
    print(f"Webhook снаружи: {response.status_code} (ожидается 401)")
    if response.status_code != 401:
        return [
            f"{settings.webhook_url} отвечает {response.status_code}, а не 401 — "
            "Caddy не проксирует /bot/* на api или домен не тот"
        ]
    return []


async def diagnose(
    settings: Settings,
    client: MaxClient | None,
    redis: Redis | None,
    *,
    check_external: bool = False,
) -> list[str]:
    """Печатает отчёт и возвращает список проблем."""
    problems: list[str] = []
    print(f"Режим бота (BOT_MODE): {settings.bot_mode}")
    print(f"Ожидаемый webhook: {settings.webhook_url}")
    print(f"MAX_BOT_USERNAME: {settings.max_bot_username or '— не задан'}")
    print(f"ADMIN_MAX_USER_IDS: задано {len(settings.admin_max_user_ids)} шт.")
    if not settings.max_bot_username:
        problems.append(
            "MAX_BOT_USERNAME не задан — не работают ссылки на бота, вход кодом "
            "и кнопки мини-приложения у модераторов"
        )
    if not settings.admin_max_user_ids:
        problems.append(
            "ADMIN_MAX_USER_IDS пуст — некому модерировать: все афиши ждут решения "
            "администратора и без него не публикуются"
        )
    if settings.bot_mode == "webhook":
        problems += config_problems(settings)
        if redis is not None:
            problems += await _worker_problems(redis)
        if check_external and settings.webhook_url.startswith("https://"):
            problems += await _external_problems(settings)
    elif redis is not None:
        problems += await _poller_problems(redis)
    if client is None:
        if "MAX_BOT_TOKEN не задан" not in problems:
            problems.append("MAX_BOT_TOKEN не задан")
        return problems

    try:
        me = await client.get_me()
    except httpx.TransportError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            problems.append(f"GET /me: {describe_error(exc)}")
        else:
            problems.append(
                f"GET /me: нет связи с {settings.max_api_base} ({type(exc).__name__}) — "
                "проверь интернет, VPN/прокси и DNS; токен тут ни при чём"
            )
        return problems
    except Exception as exc:
        problems.append(f"GET /me не удался: {type(exc).__name__} — проверь MAX_BOT_TOKEN")
        return problems
    commands = ", ".join("/" + c["name"] for c in me.get("commands") or []) or "—"
    print(f"Бот: {me.get('first_name')} (@{me.get('username')}), id {me.get('user_id')}")
    print(f"Команды бота: {commands}")
    if settings.max_bot_username and me.get("username") != settings.max_bot_username:
        problems.append(
            f"MAX_BOT_USERNAME={settings.max_bot_username}, а токен от @{me.get('username')}"
        )

    subs = await client.list_subscriptions()
    print(f"Подписки ({len(subs)}):")
    for s in subs:
        mark = "✓" if s.get("url") == settings.webhook_url else "✗ чужой URL"
        print(f"  {mark} {s.get('url')}  с {_ts(s.get('time'))}  типы: {s.get('update_types')}")
    problems += _subscription_problems(settings, subs)

    if redis is not None:
        try:
            status = await load_status(redis)
        except Exception as exc:
            status = None
            print(f"Статус последней проверки недоступен: {type(exc).__name__}")
        if status is not None:
            print(
                f"Последняя проверка подписки: {status.get('state')} "
                f"в {_ts(status.get('checked_at'))} {status.get('problems') or ''}"
            )
    return problems


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Диагностика бота MAX")
    parser.add_argument("--fix", action="store_true", help="пересоздать webhook-подписку")
    args = parser.parse_args(argv)
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
    client = (
        MaxClient(settings.max_bot_token.get_secret_value(), settings.max_api_base)
        if settings.max_bot_token is not None
        else None
    )
    try:
        if args.fix:
            print(f"Пересоздаю подписку: {await check_webhook(settings, redis, force=True)}")
            if client is not None:
                synced = await sync_commands(client)
                print(f"Команды бота: {'обновлены' if synced else 'не удалось обновить'}")
        problems = await diagnose(settings, client, redis, check_external=True)
    finally:
        if client is not None:
            await client.aclose()
        await redis.aclose()
    if problems:
        print("\nПроблемы:")
        for p in problems:
            print(f"  • {p}")
        return 1
    print("\nПроблем не найдено.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
