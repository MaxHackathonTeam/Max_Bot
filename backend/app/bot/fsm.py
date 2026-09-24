"""Состояния диалога бота (§12): FSM в Redis с TTL 24 ч, в тестах — в памяти."""

from typing import Protocol

from redis.asyncio import Redis

STATE_TTL_S = 24 * 3600

# Ждём населённый пункт: при онбординге (дальше — интересы) или из настроек.
ONBOARDING_LOCALITY = "onboarding.locality"
ONBOARDING_INTERESTS = "onboarding.interests"
SETTINGS_LOCALITY = "settings.locality"
IDLE = "idle"


class StateStore(Protocol):
    async def get(self, user_id: int) -> str: ...

    async def set(self, user_id: int, state: str) -> None: ...


class RedisStateStore:
    def __init__(self, redis: Redis, ttl_s: int = STATE_TTL_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    @staticmethod
    def _key(user_id: int) -> str:
        return f"bot:fsm:{user_id}"

    async def get(self, user_id: int) -> str:
        value = await self._redis.get(self._key(user_id))
        if value is None:
            return IDLE
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, user_id: int, state: str) -> None:
        if state == IDLE:
            await self._redis.delete(self._key(user_id))
        else:
            await self._redis.set(self._key(user_id), state, ex=self._ttl_s)


class MemoryStateStore:
    """Для тестов и запуска без Redis; TTL не соблюдается."""

    def __init__(self) -> None:
        self._states: dict[int, str] = {}

    async def get(self, user_id: int) -> str:
        return self._states.get(user_id, IDLE)

    async def set(self, user_id: int, state: str) -> None:
        if state == IDLE:
            self._states.pop(user_id, None)
        else:
            self._states[user_id] = state
