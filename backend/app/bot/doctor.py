"""Диагностика «бот молчит»: конфигурация, GET /me, GET /subscriptions, статус проверки.

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

from redis.asyncio import Redis

from app.bot.subscriptions import check_webhook, config_problems, load_status, sync_commands
from app.core.config import Settings, get_settings
from app.integrations.max import MaxClient
from app.integrations.max.client import UPDATE_TYPES


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


async def diagnose(settings: Settings, client: MaxClient | None, redis: Redis | None) -> list[str]:
    """Печатает отчёт и возвращает список проблем."""
    problems: list[str] = []
    print(f"Режим бота (BOT_MODE): {settings.bot_mode}")
    print(f"Ожидаемый webhook: {settings.webhook_url}")
    print(f"MAX_BOT_USERNAME: {settings.max_bot_username or '— не задан'}")
    print(f"ADMIN_MAX_USER_IDS: задано {len(settings.admin_max_user_ids)} шт.")
    if not settings.max_bot_username:
        problems.append("MAX_BOT_USERNAME не задан — не работают ссылки на бота и вход кодом")
    if not settings.admin_max_user_ids:
        problems.append("ADMIN_MAX_USER_IDS пуст — некому модерировать и получать заявки")
    if settings.bot_mode == "webhook":
        problems += config_problems(settings)
    if client is None:
        if "MAX_BOT_TOKEN не задан" not in problems:
            problems.append("MAX_BOT_TOKEN не задан")
        return problems

    try:
        me = await client.get_me()
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
        problems = await diagnose(settings, client, redis)
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
