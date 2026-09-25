"""DaData «Подсказки»: населённые пункты, адреса, обратное геокодирование (§7.5).

Эндпоинты suggestions.dadata.ru/suggestions/api/4_1/rs: suggest/address, geolocate/address;
заголовок `Authorization: Token <API-ключ>`.
"""

from typing import Any

import httpx

from app.integrations.geo import GeoAddress, GeoError, GeoPlace
from app.integrations.http import ExternalApiError, request_json

BASE_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
TIMEOUT_S = 5.0

# Тип населённого пункта из сокращений ФИАС → LocalityKind.
_KIND_BY_TYPE = {
    "г": "city",
    "пгт": "pgt",
    "рп": "pgt",
    "кп": "pgt",
    "п": "settlement",
    "с": "village",
    "д": "village",
    "х": "village",
    "ст-ца": "village",
    "сл": "village",
    "аул": "village",
}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def place_from_suggestion(data: dict[str, Any]) -> GeoPlace | None:
    """Населённый пункт из поля data подсказки DaData (село важнее города-округа)."""
    if data.get("settlement"):
        name, kind_type, fias_id = (
            data["settlement"],
            data.get("settlement_type"),
            data.get("settlement_fias_id"),
        )
    elif data.get("city"):
        name, kind_type, fias_id = data["city"], data.get("city_type"), data.get("city_fias_id")
    else:
        return None
    lat, lon = _float(data.get("geo_lat")), _float(data.get("geo_lon"))
    if lat is None or lon is None:
        return None
    kladr = data.get("region_kladr_id") or ""
    return GeoPlace(
        name=name,
        kind=_KIND_BY_TYPE.get(kind_type or "", "other"),
        lat=lat,
        lon=lon,
        region=data.get("region_with_type"),
        region_code=kladr[:2] or None,
        municipality=data.get("area_with_type") or data.get("city_district_with_type"),
        fias_id=fias_id,
        source="dadata",
    )


class DadataGeoProvider:
    code = "dadata"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            timeout=TIMEOUT_S,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            data = await request_json(self._http, "dadata", "POST", path, json=body)
        except ExternalApiError as exc:
            raise GeoError(str(exc)) from exc
        return list(data.get("suggestions") or [])

    async def suggest_localities(self, query: str, limit: int = 5) -> list[GeoPlace]:
        suggestions = await self._post(
            "/suggest/address",
            {
                "query": query,
                "count": limit,
                "from_bound": {"value": "city"},
                "to_bound": {"value": "settlement"},
            },
        )
        places = [place_from_suggestion(s.get("data") or {}) for s in suggestions]
        return [p for p in places if p is not None]

    async def reverse_locality(self, lat: float, lon: float) -> GeoPlace | None:
        suggestions = await self._post(
            "/geolocate/address", {"lat": lat, "lon": lon, "count": 1, "radius_meters": 1000}
        )
        for s in suggestions:
            place = place_from_suggestion(s.get("data") or {})
            if place is not None:
                return place
        return None

    async def suggest_addresses(self, query: str, limit: int = 5) -> list[GeoAddress]:
        suggestions = await self._post("/suggest/address", {"query": query, "count": limit})
        result = []
        for s in suggestions:
            data = s.get("data") or {}
            result.append(
                GeoAddress(
                    value=s.get("value") or "",
                    lat=_float(data.get("geo_lat")),
                    lon=_float(data.get("geo_lon")),
                    fias_id=data.get("fias_id"),
                    locality=place_from_suggestion(data),
                )
            )
        return result
