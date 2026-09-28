"""Состояния диалога бота (§12): FSM в Redis с TTL 24 ч, в тестах — в памяти.

Кроме имени состояния хранятся данные шага (JSON): поля черновика в мастере «Добавить афишу».
Сброс в IDLE стирает и состояние, и данные.
"""

import json
from typing import Any, Protocol

from redis.asyncio import Redis

STATE_TTL_S = 24 * 3600

# Ждём населённый пункт: при онбординге (дальше — интересы), из настроек или /city (→ меню).
ONBOARDING_LOCALITY = "onboarding.locality"
ONBOARDING_INTERESTS = "onboarding.interests"
SETTINGS_LOCALITY = "settings.locality"
CITY_LOCALITY = "city.locality"
# Админ пишет причину отказа: admin.reason:<e|v>:<id>.
ADMIN_REASON = "admin.reason"
# /find: следующее сообщение — поисковый запрос.
FIND_QUERY = "find.query"
# Мастер «Добавить афишу»: add.<шаг>, шаги — app.bot.add_event.STEPS.
ADD_PREFIX = "add."
IDLE = "idle"


class StateStore(Protocol):
    async def get(self, user_id: int) -> str: ...

    async def set(self, user_id: int, state: str) -> None: ...

    async def get_data(self, user_id: int) -> dict[str, Any]: ...

    async def set_data(self, user_id: int, data: dict[str, Any]) -> None: ...


class RedisStateStore:
    def __init__(self, redis: Redis, ttl_s: int = STATE_TTL_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    @staticmethod
    def _key(user_id: int) -> str:
        return f"bot:fsm:{user_id}"

    @staticmethod
    def _data_key(user_id: int) -> str:
        return f"bot:fsm:data:{user_id}"

    async def get(self, user_id: int) -> str:
        value = await self._redis.get(self._key(user_id))
        if value is None:
            return IDLE
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, user_id: int, state: str) -> None:
        if state == IDLE:
            await self._redis.delete(self._key(user_id), self._data_key(user_id))
        else:
            await self._redis.set(self._key(user_id), state, ex=self._ttl_s)

    async def get_data(self, user_id: int) -> dict[str, Any]:
        raw = await self._redis.get(self._data_key(user_id))
        if raw is None:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    async def set_data(self, user_id: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        await self._redis.set(self._data_key(user_id), payload, ex=self._ttl_s)


class MemoryStateStore:
    """Для тестов и запуска без Redis; TTL не соблюдается."""

    def __init__(self) -> None:
        self._states: dict[int, str] = {}
        self._data: dict[int, str] = {}

    async def get(self, user_id: int) -> str:
        return self._states.get(user_id, IDLE)

    async def set(self, user_id: int, state: str) -> None:
        if state == IDLE:
            self._states.pop(user_id, None)
            self._data.pop(user_id, None)
        else:
            self._states[user_id] = state

    async def get_data(self, user_id: int) -> dict[str, Any]:
        raw = self._data.get(user_id)
        return dict(json.loads(raw)) if raw else {}

    async def set_data(self, user_id: int, data: dict[str, Any]) -> None:
        # Через JSON, как в Redis: в данных шага не окажется ничего несериализуемого.
        self._data[user_id] = json.dumps(data, ensure_ascii=False)
