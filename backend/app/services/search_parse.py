"""Фраза пользователя → фильтры ленты. Только детерминированные правила, без внешних вызовов.

Распознаём дату, время, цену, Пушкинскую карту, категории (по основам слов) и населённый пункт
(по основам названий из справочника, с опечатками — через pg_trgm). Остаток уходит в FTS.
"""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geo import Locality
from app.parsing import extract
from app.parsing.dictionaries import STOP_WORDS
from app.services.categories import BY_SLUG
from app.services.localities import DEFAULT_TIMEZONE

MAX_PHRASE = 200
# Порог похожести названия НП на слово запроса (pg_trgm similarity) для опечаток.
LOCALITY_SIMILARITY = 0.5
FUZZY_MIN_LEN = 5


@dataclass(frozen=True)
class ParsedSearch:
    date: str | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    time_from: int | None = None
    free: bool = False
    price_max: int | None = None
    pushkin: bool = False
    categories: tuple[str, ...] = ()
    locality_id: int | None = None
    locality_name: str | None = None
    q: str | None = None
    chips: tuple[str, ...] = ()
    # Ничего не распознано — весь текст ушёл в полнотекстовый поиск.
    fallback: bool = False


def _inside(token: extract.Token, spans: list[extract.Span]) -> bool:
    return any(start <= token.start and token.end <= end for start, end in spans)


async def _locality_by_stems(
    session: AsyncSession, tokens: list[extract.Token]
) -> tuple[Locality, list[extract.Span]] | None:
    """НП, все слова названия которого подряд встречаются в запросе (в любой словоформе)."""
    stems = [t.stem for t in tokens]
    places = list(await session.scalars(select(Locality)))
    # Многословные названия раньше: «Старая Русса» важнее случайного однословного совпадения.
    places.sort(key=lambda p: (-len(p.name.split()), -(p.population or 0), p.id))
    for place in places:
        words = [extract.stem(w.text) for w in extract.tokenize(place.name)]
        if not words:
            continue
        for i in range(len(stems) - len(words) + 1):
            if stems[i : i + len(words)] == words:
                spans = [(tokens[j].start, tokens[j].end) for j in range(i, i + len(words))]
                return place, spans
    return None


async def _locality_fuzzy(
    session: AsyncSession, tokens: list[extract.Token]
) -> tuple[Locality, list[extract.Span]] | None:
    for token in tokens:
        if len(token.text) < FUZZY_MIN_LEN:
            continue
        similarity = func.similarity(Locality.name, token.text)
        place = await session.scalar(
            select(Locality)
            .where(similarity >= LOCALITY_SIMILARITY)
            .order_by(desc(similarity), Locality.id)
            .limit(1)
        )
        if place is not None:
            return place, [(token.start, token.end)]
    return None


def _today(now: dt.datetime | None) -> dt.date:
    moment = now or dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    return moment.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()


async def parse(session: AsyncSession, text: str, now: dt.datetime | None = None) -> ParsedSearch:
    phrase = " ".join(text.split())[:MAX_PHRASE]
    if not phrase:
        return ParsedSearch()
    today = _today(now)
    spans: list[extract.Span] = []
    chips: list[str] = []

    date_hit = extract.find_date(phrase, today)
    if date_hit:
        spans.extend(date_hit.spans)
        chips.append(date_hit.label)
    time_hit = extract.find_time_from(phrase)
    if time_hit:
        spans.append(time_hit[1])
        chips.append(f"после {time_hit[0]}:00")
    free_span = extract.find_free(phrase)
    if free_span:
        spans.append(free_span)
        chips.append("бесплатно")
    price_hit = None if free_span else extract.find_price_max(phrase)
    if price_hit:
        spans.append(price_hit[1])
        chips.append(f"до {price_hit[0]} ₽")
    pushkin_span = extract.find_pushkin(phrase)
    if pushkin_span:
        spans.append(pushkin_span)
        chips.append("Пушкинская карта")

    tokens = [t for t in extract.tokenize(phrase) if not _inside(t, spans)]
    categories = extract.find_categories(tokens)
    spans.extend(categories.spans)
    chips.extend(BY_SLUG[slug].name for slug in categories.slugs)

    rest = [
        t for t in tokens if not _inside(t, spans) and extract.normalize(t.text) not in STOP_WORDS
    ]
    place_hit = await _locality_by_stems(session, rest) or await _locality_fuzzy(session, rest)
    place = place_hit[0] if place_hit else None
    if place_hit:
        spans.extend(place_hit[1])
        chips.append(place_hit[0].name)

    leftover = [
        t.text
        for t in extract.tokenize(phrase)
        if not _inside(t, spans) and extract.normalize(t.text) not in STOP_WORDS
    ]
    return ParsedSearch(
        date=date_hit.preset if date_hit else None,
        date_from=date_hit.date_from if date_hit else None,
        date_to=date_hit.date_to if date_hit else None,
        time_from=time_hit[0] if time_hit else None,
        free=free_span is not None,
        price_max=price_hit[0] if price_hit else None,
        pushkin=pushkin_span is not None,
        categories=tuple(categories.slugs),
        locality_id=place.id if place else None,
        locality_name=place.name if place else None,
        q=" ".join(leftover) or None,
        chips=tuple(chips),
        fallback=not chips,
    )
