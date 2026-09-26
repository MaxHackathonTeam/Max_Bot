"""Общие типы источников событий для импортного конвейера."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class RawEvent:
    source_id: str
    title: str
    description: str | None
    starts_at: datetime
    venue_name: str
    address: str | None = None
    locality: str | None = None
    region_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    category: str | None = None
    price_min: float | None = None
    ticket_url: str | None = None
    pushkin_card: bool = False
    organization_id: str | None = None
    inn: str | None = None
    source_url: str | None = None
    raw: dict[str, object] | None = None
    demo: bool = False


class EventSource(Protocol):
    code: str

    def fetch(
        self, region_codes: list[str], date_from: date, date_to: date
    ) -> AsyncIterator[RawEvent]: ...
