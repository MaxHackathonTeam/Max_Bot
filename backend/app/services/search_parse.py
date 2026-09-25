"""Фраза пользователя → проверенные фильтры; при ошибке LLM текст остаётся для FTS."""

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.runner import LlmRunner
from app.llm.schemas import SearchFiltersOut
from app.models.geo import Locality
from app.services.categories import BY_SLUG

_WORDS = {
    "концерт": "concert",
    "музык": "concert",
    "кино": "cinema",
    "спектакл": "theatre",
    "театр": "theatre",
    "выставк": "exhibition",
    "музе": "exhibition",
    "спорт": "sport",
    "экскурс": "excursion",
}


@dataclass(frozen=True)
class ParsedSearch:
    date: str | None = None
    free: bool = False
    pushkin: bool = False
    categories: tuple[str, ...] = ()
    locality_id: int | None = None
    locality_name: str | None = None
    q: str | None = None
    chips: tuple[str, ...] = ()
    fallback: bool = False


async def parse(session: AsyncSession, text: str, llm: LlmRunner | None = None) -> ParsedSearch:
    phrase = text.strip()[:200]
    if not phrase:
        return ParsedSearch()
    result = None
    if llm is not None:
        try:
            answer = await asyncio.wait_for(
                llm.run_json(
                    "search_parse",
                    "search_parse",
                    SearchFiltersOut,
                    text=phrase,
                    categories=", ".join(BY_SLUG),
                ),
                timeout=2.8,
            )
            result = answer.value
        except (TimeoutError, OSError):
            pass
    low = phrase.casefold()
    date = result.date if result else None
    free = result.free if result else False
    pushkin = result.pushkin if result else False
    category = result.category if result and result.category in BY_SLUG else None
    if not date:
        if re.search(r"\bсегодня\b", low):
            date = "today"
        elif re.search(r"\bзавтра\b", low):
            date = "tomorrow"
        elif re.search(r"\b(выходн\w*|суббот\w*|воскресень\w*)\b", low):
            date = "weekend"
    free = free or bool(re.search(r"\bбесплатн\w*\b", low))
    pushkin = pushkin or "пушкинск" in low
    if category is None:
        category = next((slug for stem, slug in _WORDS.items() if stem in low), None)
    # Только точное вхождение названия существующего НП; LLM-подсказку сверяем с БД.
    places = list(await session.scalars(select(Locality).order_by(Locality.name.desc())))
    place = next(
        (p for p in places if re.search(r"(?<!\w)" + re.escape(p.name.casefold()) + r"\w*", low)),
        None,
    )
    chips = [
        x
        for x in (
            date,
            "бесплатно" if free else None,
            "Пушкинская карта" if pushkin else None,
            BY_SLUG[category].name if category else None,
            place.name if place else None,
        )
        if x
    ]
    remainder = phrase
    for pattern in (
        r"\b(?:сегодня|завтра|выходн\w*|суббот\w*|воскресень\w*)\b",
        r"\bбесплатн\w*\b",
        r"\b(?:по\s+)?пушкинск\w*\s+карт\w*\b",
    ):
        remainder = re.sub(pattern, " ", remainder, flags=re.I)
    if place:
        remainder = re.sub(re.escape(place.name) + r"\w*", " ", remainder, flags=re.I)
    remainder = re.sub(r"\b(?:в|на|по|рядом|со|мной)\b", " ", remainder, flags=re.I)
    remainder = " ".join(remainder.split())
    # Если LLM недоступна, оставляем исходную фразу в FTS, если нет надёжных фильтров.
    return ParsedSearch(
        date,
        free,
        pushkin,
        (category,) if category else (),
        place.id if place else None,
        place.name if place else None,
        remainder or None,
        tuple(chips),
        result is None,
    )
