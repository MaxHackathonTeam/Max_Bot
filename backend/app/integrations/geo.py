"""Геокодеры (§7.5): интерфейс GeoProvider, цепочка DaData → Nominatim и кэш в Redis."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Коды регионов (КЛАДР, 2 цифры) по ISO 3166-2 — для Nominatim, который отдаёт только ISO.
ISO_TO_REGION_CODE = {"RU-NGR": "53", "RU-TA": "16", "RU-MOW": "77", "RU-SPE": "78"}


@dataclass(frozen=True)
class GeoPlace:
    """Населённый пункт от геокодера."""

    name: str
    kind: str  # LocalityKind
    lat: float
    lon: float
    region: str | None = None
    region_code: str | None = None
    municipality: str | None = None
    fias_id: str | None = None
    source: str = ""


@dataclass(frozen=True)
class GeoAddress:
    """Подсказка адреса (для площадок)."""

    value: str
    lat: float | None
    lon: float | None
    fias_id: str | None = None
    locality: GeoPlace | None = None


class GeoProvider(Protocol):
    code: str

    async def suggest_localities(self, query: str, limit: int = 5) -> list[GeoPlace]: ...

    async def reverse_locality(self, lat: float, lon: float) -> GeoPlace | None: ...

    async def suggest_addresses(self, query: str, limit: int = 5) -> list[GeoAddress]: ...


class GeoError(Exception):
    """Геокодер недоступен или ответил ошибкой."""


class ChainGeoProvider:
    """Опрашивает провайдеров по очереди: первый непустой ответ без ошибки побеждает."""

    def __init__(self, providers: list[GeoProvider]) -> None:
        self._providers = providers
        self.code = "+".join(p.code for p in providers)

    async def suggest_localities(self, query: str, limit: int = 5) -> list[GeoPlace]:
        for provider in self._providers:
            try:
                places = await provider.suggest_localities(query, limit)
            except GeoError:
                continue
            if places:
                return places
        return []

    async def reverse_locality(self, lat: float, lon: float) -> GeoPlace | None:
        for provider in self._providers:
            try:
                place = await provider.reverse_locality(lat, lon)
            except GeoError:
                continue
            if place is not None:
                return place
        return None

    async def suggest_addresses(self, query: str, limit: int = 5) -> list[GeoAddress]:
        for provider in self._providers:
            try:
                addresses = await provider.suggest_addresses(query, limit)
            except GeoError:
                continue
            if addresses:
                return addresses
        return []


def _place(data: dict[str, Any]) -> GeoPlace:
    return GeoPlace(**data)


def _address(data: dict[str, Any]) -> GeoAddress:
    locality = data.pop("locality", None)
    return GeoAddress(**data, locality=_place(locality) if locality else None)


class CachedGeoProvider:
    """Кэш ответов в Redis (30 дней). Ошибки Redis не ломают поиск — идём в провайдер."""

    def __init__(self, inner: GeoProvider, redis: Redis, ttl_s: int = 30 * 24 * 3600) -> None:
        self._inner = inner
        self._redis = redis
        self._ttl_s = ttl_s
        self.code = inner.code

    def _key(self, method: str, *args: object) -> str:
        raw = json.dumps([method, *args], ensure_ascii=False)
        return f"geo:{self.code}:{hashlib.sha256(raw.encode()).hexdigest()}"

    async def _get(self, key: str) -> Any:
        try:
            value = await self._redis.get(key)
        except Exception as exc:
            log.warning("geo_cache_unavailable", error=type(exc).__name__)
            return None
        return json.loads(value) if value is not None else None

    async def _set(self, key: str, value: Any) -> None:
        try:
            await self._redis.set(key, json.dumps(value, ensure_ascii=False), ex=self._ttl_s)
        except Exception as exc:
            log.warning("geo_cache_unavailable", error=type(exc).__name__)

    async def suggest_localities(self, query: str, limit: int = 5) -> list[GeoPlace]:
        key = self._key("loc", query.casefold(), limit)
        cached = await self._get(key)
        if cached is not None:
            return [_place(p) for p in cached]
        places = await self._inner.suggest_localities(query, limit)
        await self._set(key, [asdict(p) for p in places])
        return places

    async def reverse_locality(self, lat: float, lon: float) -> GeoPlace | None:
        # Округление до ~100 м: соседние точки попадают в один ключ.
        key = self._key("rev", round(lat, 3), round(lon, 3))
        cached = await self._get(key)
        if cached is not None:
            return _place(cached) if cached else None
        place = await self._inner.reverse_locality(lat, lon)
        await self._set(key, asdict(place) if place else {})
        return place

    async def suggest_addresses(self, query: str, limit: int = 5) -> list[GeoAddress]:
        key = self._key("addr", query.casefold(), limit)
        cached = await self._get(key)
        if cached is not None:
            return [_address(a) for a in cached]
        addresses = await self._inner.suggest_addresses(query, limit)
        await self._set(key, [asdict(a) for a in addresses])
        return addresses
