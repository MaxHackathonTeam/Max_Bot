"""DaData «Организация по ИНН или ОГРН» (findById/party) — ЕГРЮЛ/ЕГРИП для верификации §5.3 B.1.

POST suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party, тело {"query": "<ИНН>"},
заголовок `Authorization: Token <API-ключ>`. Статус юрлица — data.state.status (ACTIVE и др.).
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.integrations.dadata.client import BASE_URL, TIMEOUT_S
from app.integrations.http import ExternalApiError, request_json


class RegistryError(Exception):
    """Реестр недоступен (сеть, ключ, лимит)."""


@dataclass(frozen=True)
class PartyInfo:
    inn: str
    ogrn: str | None
    kind: str  # LEGAL | INDIVIDUAL
    status: str | None
    name_full: str | None
    name_short: str | None
    # Названия без организационно-правовой формы — для сравнения с введённым.
    names_plain: tuple[str, ...]
    address: str | None
    region: str | None
    region_code: str | None
    raw: dict[str, Any]

    @property
    def display_name(self) -> str:
        return self.name_short or self.name_full or self.inn


class PartyRegistry(Protocol):
    async def find_by_inn(self, inn: str) -> PartyInfo | None: ...


def party_from_suggestion(suggestion: dict[str, Any]) -> PartyInfo:
    data = suggestion.get("data") or {}
    name = data.get("name") or {}
    address = data.get("address") or {}
    address_data = address.get("data") or {}
    kladr = address_data.get("region_kladr_id") or ""
    plain = tuple(n for n in (name.get("short"), name.get("full")) if isinstance(n, str) and n)
    return PartyInfo(
        inn=str(data.get("inn") or ""),
        ogrn=data.get("ogrn"),
        kind=str(data.get("type") or "LEGAL"),
        status=(data.get("state") or {}).get("status"),
        name_full=name.get("full_with_opf"),
        name_short=name.get("short_with_opf") or suggestion.get("value"),
        names_plain=plain or tuple(n for n in (suggestion.get("value"),) if n),
        address=address.get("value"),
        region=address_data.get("region_with_type"),
        region_code=kladr[:2] or None,
        raw=suggestion,
    )


class DadataPartyRegistry:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            timeout=TIMEOUT_S,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def find_by_inn(self, inn: str) -> PartyInfo | None:
        try:
            data = await request_json(
                self._http, "dadata", "POST", "/findById/party", json={"query": inn, "count": 1}
            )
        except ExternalApiError as exc:
            raise RegistryError(str(exc)) from exc
        suggestions = list(data.get("suggestions") or [])
        return party_from_suggestion(suggestions[0]) if suggestions else None
