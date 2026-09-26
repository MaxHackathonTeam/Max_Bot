"""Адаптер экспорта PRO.Культура.РФ v2.5 и маркированная локальная фикстура."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.sources.base import RawEvent

API = "https://pro.culture.ru/api/2.5/"
FIXTURE = Path(__file__).resolve().parents[3] / "data/fixtures/proculture.json"


def normalize(item: dict[str, Any], *, demo: bool = False) -> RawEvent | None:
    """Извлечь устойчивую часть схемы API; неизвестная схема не становится событием."""
    source_id = item.get("_id", item.get("id"))
    title = item.get("name", item.get("title"))
    if source_id is None or not isinstance(title, str) or not title.strip():
        return None
    organization = item.get("organization") or {}
    place = item.get("place") or item.get("venue") or {}
    locale = organization.get("locale") or item.get("locale") or {}
    event_date = item.get("dateStart") or item.get("startDate") or item.get("date")
    try:
        starts = datetime.fromisoformat(str(event_date).replace("Z", "+00:00"))
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None
    point = place.get("point") or item.get("point") or {}
    lat = point.get("lat") or place.get("latitude")
    lon = point.get("lon") or place.get("longitude")
    inn = organization.get("inn") or organization.get("INN")
    return RawEvent(
        source_id=str(source_id),
        title=title.strip(),
        description=item.get("description"),
        starts_at=starts,
        venue_name=str(
            place.get("name") or item.get("placeName") or organization.get("name") or "Площадка"
        ),
        address=place.get("address") or item.get("address"),
        locality=locale.get("name") or item.get("locality"),
        region_code=str(
            (organization.get("subordination") or {}).get("code") or item.get("regionCode") or ""
        ),
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        category=item.get("category"),
        price_min=item.get("price"),
        ticket_url=item.get("url") or item.get("ticketUrl"),
        pushkin_card=bool(item.get("isPushkinsCard", False)),
        organization_id=str(organization.get("_id")) if organization.get("_id") else None,
        inn=str(inn) if inn else None,
        source_url=item.get("url"),
        raw=item,
        demo=demo,
    )


class ProCultureSource:
    code = "proculture"

    def __init__(self, api_key: str | None, *, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch(
        self, region_codes: list[str], date_from: date, date_to: date
    ) -> AsyncIterator[RawEvent]:
        if not self.api_key:
            records = json.loads(FIXTURE.read_text(encoding="utf-8"))
            for item in records.get("events", []):
                event = normalize(item, demo=True)
                if event and date_from <= event.starts_at.date() <= date_to:
                    yield event
            return
        # Экспорт принимает API-ключ как query param; передаём региональные id через
        # subordinations только если они числовые (коды регионов не являются id API).
        params: dict[str, str] = {"apiKey": self.api_key}
        numeric_regions = [code for code in region_codes if code.isdigit()]
        if numeric_regions:
            params["subordinations"] = ",".join(numeric_regions)
        response = await self.client.get(urljoin(API, "pushkinsCardEvents"), params=params)
        response.raise_for_status()
        payload = response.json()
        records = (
            payload.get("pushkinsCardEvents", payload.get("events", []))
            if isinstance(payload, dict)
            else payload
        )
        if isinstance(records, dict):
            records = [records]
        for item in records if isinstance(records, list) else []:
            event = normalize(item)
            if event and date_from <= event.starts_at.date() <= date_to:
                yield event
