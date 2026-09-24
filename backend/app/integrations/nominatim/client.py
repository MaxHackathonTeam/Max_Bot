"""Nominatim (OSM) — запасной геокодер (§7.5).

Политика использования: не чаще 1 запроса в секунду, User-Agent с контактом, кэширование.
Ограничение частоты — общее для всех процессов через ключ в Redis.
"""

import asyncio
from typing import Any

import httpx
from redis.asyncio import Redis

from app.integrations.geo import ISO_TO_REGION_CODE, GeoAddress, GeoError, GeoPlace
from app.integrations.http import ExternalApiError, request_json

BASE_URL = "https://nominatim.openstreetmap.org"
TIMEOUT_S = 8.0
THROTTLE_KEY = "nominatim:throttle"
THROTTLE_WAIT_S = 3.0

_KIND_BY_TYPE = {
    "city": "city",
    "town": "town",
    "village": "village",
    "hamlet": "village",
    "isolated_dwelling": "village",
}
_NAME_KEYS = ("city", "town", "village", "hamlet", "isolated_dwelling")


def place_from_item(item: dict[str, Any]) -> GeoPlace | None:
    address = item.get("address") or {}
    kind_key = item.get("addresstype") or ""
    name = item.get("name") if kind_key in _KIND_BY_TYPE else None
    if not name:
        # Обратное геокодирование и адреса отдают улицу/дом — берём НП из адреса.
        kind_key, name = next(((k, address[k]) for k in _NAME_KEYS if address.get(k)), ("", None))
    if not name:
        return None
    iso = address.get("ISO3166-2-lvl4") or ""
    return GeoPlace(
        name=name,
        kind=_KIND_BY_TYPE.get(kind_key, "other"),
        lat=float(item["lat"]),
        lon=float(item["lon"]),
        region=address.get("state"),
        region_code=ISO_TO_REGION_CODE.get(iso),
        municipality=address.get("county") or address.get("municipality"),
        source="nominatim",
    )


class NominatimGeoProvider:
    code = "nominatim"

    def __init__(
        self,
        user_agent: str,
        redis: Redis | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": user_agent, "Accept-Language": "ru"},
            timeout=TIMEOUT_S,
            transport=transport,
        )
        self._redis = redis
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _throttle(self) -> None:
        if self._redis is None:
            await asyncio.sleep(1.0)
            return
        waited = 0.0
        while waited < THROTTLE_WAIT_S:
            try:
                if await self._redis.set(THROTTLE_KEY, "1", nx=True, px=1100):
                    return
            except Exception:
                await asyncio.sleep(1.0)  # Redis недоступен — хотя бы пауза в процессе
                return
            await asyncio.sleep(0.25)
            waited += 0.25
        raise GeoError("nominatim: превышена частота запросов")

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        # Lock — один запрос за раз в процессе; ключ в Redis — 1 запрос/с на все процессы.
        async with self._lock:
            await self._throttle()
            try:
                return await request_json(
                    self._http, "nominatim", "GET", path, params=params, retries=1
                )
            except ExternalApiError as exc:
                raise GeoError(str(exc)) from exc

    async def suggest_localities(self, query: str, limit: int = 5) -> list[GeoPlace]:
        items = await self._get(
            "/search",
            {
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "countrycodes": "ru",
                "featureType": "settlement",
                "limit": limit,
            },
        )
        places = [place_from_item(item) for item in items or []]
        return [p for p in places if p is not None]

    async def reverse_locality(self, lat: float, lon: float) -> GeoPlace | None:
        item = await self._get(
            "/reverse",
            {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14, "addressdetails": 1},
        )
        if not item or "error" in item:
            return None
        return place_from_item(item)

    async def suggest_addresses(self, query: str, limit: int = 5) -> list[GeoAddress]:
        items = await self._get(
            "/search",
            {
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "countrycodes": "ru",
                "limit": limit,
            },
        )
        return [
            GeoAddress(
                value=item.get("display_name") or "",
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                locality=place_from_item({**item, "addresstype": ""}),
            )
            for item in items or []
        ]
