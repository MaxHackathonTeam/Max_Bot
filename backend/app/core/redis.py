"""Общий клиент Redis."""

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    client: Redis = Redis.from_url(
        get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2
    )
    return client
