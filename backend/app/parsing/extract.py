"""Детерминированное извлечение фактов из русского текста: даты, время, цены, контакты, адрес.

Без внешних вызовов и без LLM. Функции возвращают найденное значение и позиции в тексте,
чтобы вызывающий мог вырезать распознанное (остаток уходит в полнотекстовый поиск).
"""

import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any

import snowballstemmer

from app.parsing.dictionaries import CATEGORY_KEYWORDS, MONTHS, WEEKDAYS

Span = tuple[int, int]

_WORD_RE = re.compile(r"[a-zа-яё0-9]+(?:-[a-zа-яё0-9]+)*", re.IGNORECASE)
_MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_WEEKDAY_LABELS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


@lru_cache
def _stemmer() -> Any:
    return snowballstemmer.stemmer("russian")


def normalize(word: str) -> str:
    return word.casefold().replace("ё", "е")


def stem(word: str) -> str:
    return str(_stemmer().stemWord(normalize(word)))


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int

    @property
    def stem(self) -> str:
        return stem(self.text)


def tokenize(text: str) -> list[Token]:
    return [Token(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def date_label(day: date) -> str:
    return f"{day.day} {_MONTH_NAMES[day.month - 1]}"


# --- Даты ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DateHit:
    """Найденная дата: пресет ленты (today/tomorrow/weekend) или явный период."""

    label: str
    spans: tuple[Span, ...]
    preset: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def _future(day: date, today: date) -> date:
    # «15 октября», сказанное в ноябре, — это октябрь следующего года.
    return day if day >= today else day.replace(year=day.year + 1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


_RELATIVE = (
    (re.compile(r"\bпослезавтра\b", re.I), "послезавтра", 2),
    (re.compile(r"\bсегодня\b", re.I), "сегодня", 0),
    (re.compile(r"\bзавтра\b", re.I), "завтра", 1),
)
_WEEKEND_RE = re.compile(r"\b(?:(?:на|в)\s+)?(?:эти\s+|этих\s+|ближайшие\s+)?выходн\w*\b", re.I)
_WEEK_RE = re.compile(r"\b(?:на\s+)?этой\s+неделе\b", re.I)
_WEEKDAY_RE = re.compile(
    r"\b(?:(?:в|во)\s+)?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b", re.I
)
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\b", re.I)
_NUMERIC_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?![\d.])")


def _month_of(word: str) -> int | None:
    low = normalize(word)
    for prefix, month in MONTHS.items():
        if low.startswith(prefix):
            return month
    return None


def find_explicit_dates(text: str, today: date) -> list[tuple[date, Span]]:
    """Все явные даты в тексте: «15 октября», «15.10», «15.10.2026»."""
    found: list[tuple[date, Span]] = []
    for m in _DAY_MONTH_RE.finditer(text):
        month = _month_of(m.group(2))
        if month is None:
            continue
        day = _safe_date(today.year, month, int(m.group(1)))
        if day is not None:
            found.append((_future(day, today), m.span()))
    for m in _NUMERIC_DATE_RE.finditer(text):
        # «18.30» — время, а не дата: месяц больше 12 отсекает его.
        year_raw = m.group(3)
        year = today.year if year_raw is None else int(year_raw) % 100 + 2000
        day = _safe_date(year, int(m.group(2)), int(m.group(1)))
        if day is not None:
            found.append((day if year_raw else _future(day, today), m.span()))
    return sorted(found, key=lambda item: item[1])


def find_date(text: str, today: date) -> DateHit | None:
    """Дата запроса. Приоритет: выходные → относительные → неделя → день недели → явная дата."""
    if m := _WEEKEND_RE.search(text):
        return DateHit("выходные", (m.span(),), preset="weekend")
    for pattern, label, shift in _RELATIVE:
        if m := pattern.search(text):
            if shift == 0:
                return DateHit(label, (m.span(),), preset="today")
            if shift == 1:
                return DateHit(label, (m.span(),), preset="tomorrow")
            day = today + timedelta(days=shift)
            return DateHit(label, (m.span(),), date_from=day, date_to=day)
    if m := _WEEK_RE.search(text):
        sunday = today + timedelta(days=6 - today.weekday())
        return DateHit("на этой неделе", (m.span(),), date_from=today, date_to=sunday)
    if m := _WEEKDAY_RE.search(text):
        weekday = WEEKDAYS[normalize(m.group(1))]
        day = today + timedelta(days=(weekday - today.weekday()) % 7)
        return DateHit(_WEEKDAY_LABELS[weekday], (m.span(),), date_from=day, date_to=day)
    explicit = find_explicit_dates(text, today)
    if explicit:
        day, span = explicit[0]
        return DateHit(date_label(day), (span,), date_from=day, date_to=day)
    return None


# --- Время -----------------------------------------------------------------------------

_AFTER_RE = re.compile(r"\b(?:после|позже)\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*ч\w*)?\b", re.I)
_EVENING_RE = re.compile(r"\bвечер\w*\b", re.I)
_TIME_RE = re.compile(r"(?<![\d.])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d.])")
_TIME_WORD_RE = re.compile(r"\bв\s+([01]?\d|2[0-3])\s*(?:ч\b|час\w*)", re.I)
EVENING_HOUR = 17


def find_time_from(text: str) -> tuple[int, Span] | None:
    """«после 18», «вечером» → час, с которого искать."""
    m = _AFTER_RE.search(text)
    if m is not None and int(m.group(1)) <= 23:
        return int(m.group(1)), m.span()
    if m := _EVENING_RE.search(text):
        return EVENING_HOUR, m.span()
    return None


def find_times(text: str) -> list[tuple[time, Span]]:
    """Время начала в тексте анонса: «18:00», «в 18.30», «в 19 часов»."""
    found = [(time(int(m.group(1)), int(m.group(2))), m.span()) for m in _TIME_RE.finditer(text)]
    found += [(time(int(m.group(1))), m.span()) for m in _TIME_WORD_RE.finditer(text)]
    return sorted(found, key=lambda item: item[1])


# --- Цены ------------------------------------------------------------------------------

_CURRENCY = r"(?:₽|руб\w*\.?|р\.|р\b)"
_FREE_RE = re.compile(
    r"\bбесплатн\w*\b|\bвход\s+свободный\b|\bсвободный\s+вход\b|\bвход\s+free\b", re.I
)
_PUSHKIN_RE = re.compile(r"\b(?:по\s+)?пушкинск\w*(?:\s+карт\w*)?", re.I)
_PRICE_MAX_RE = re.compile(r"\b(?:до|не\s+дороже)\s+(\d[\d ]{0,6}?)\s*" + _CURRENCY, re.I)
_PRICE_RANGE_RE = re.compile(
    r"\b(\d[\d ]{0,6}?)\s*(?:" + _CURRENCY + r")?\s*(?:-|–|—|до)\s*(\d[\d ]{0,6}?)\s*" + _CURRENCY,
    re.I,
)
_PRICE_RE = re.compile(r"\b(\d[\d ]{0,6}?)\s*" + _CURRENCY, re.I)
_DONATION_RE = re.compile(r"\bдонат\w*\b|\bпожертвован\w*\b|\bсколько\s+не\s+жалко\b", re.I)


def _amount(raw: str) -> int:
    return int(raw.replace(" ", ""))


def find_free(text: str) -> Span | None:
    m = _FREE_RE.search(text)
    return m.span() if m else None


def find_pushkin(text: str) -> Span | None:
    m = _PUSHKIN_RE.search(text)
    return m.span() if m else None


def find_price_max(text: str) -> tuple[int, Span] | None:
    """«до 500 ₽» → верхняя граница цены для поиска."""
    m = _PRICE_MAX_RE.search(text)
    return (_amount(m.group(1)), m.span()) if m else None


@dataclass(frozen=True)
class PriceHit:
    price_type: str
    price_min: Decimal | None = None
    price_max: Decimal | None = None


def find_price(text: str) -> PriceHit | None:
    """Цена из анонса: бесплатно, донат, «300–500 ₽», «500 руб»."""
    if _FREE_RE.search(text):
        return PriceHit("free")
    if _DONATION_RE.search(text):
        return PriceHit("donation")
    if m := _PRICE_RANGE_RE.search(text):
        low, high = sorted((_amount(m.group(1)), _amount(m.group(2))))
        if high > 0:
            return PriceHit("paid", Decimal(low), Decimal(high))
    prices = [p for p in (_amount(m.group(1)) for m in _PRICE_RE.finditer(text)) if p > 0]
    if prices:
        return PriceHit("paid", Decimal(min(prices)), Decimal(max(prices)))
    return None


# --- Категории -------------------------------------------------------------------------


@lru_cache
def _category_stems() -> dict[str, str]:
    stems: dict[str, str] = {}
    for slug, words in CATEGORY_KEYWORDS.items():
        for word in words:
            stems.setdefault(stem(word), slug)
    return stems


@dataclass
class CategoryHit:
    slugs: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)


def find_categories(tokens: list[Token]) -> CategoryHit:
    """Категории по ключевым словам с учётом словоформ, в порядке появления."""
    table = _category_stems()
    hit = CategoryHit()
    for token in tokens:
        slug = table.get(token.stem)
        if slug is None:
            continue
        hit.spans.append((token.start, token.end))
        if slug not in hit.slugs:
            hit.slugs.append(slug)
    return hit


def cut(text: str, spans: list[Span]) -> str:
    """Текст без указанных фрагментов, с нормализованными пробелами."""
    out, pos = [], 0
    for start, end in sorted(spans):
        out.append(text[pos : max(pos, start)])
        pos = max(pos, end)
    out.append(text[pos:])
    return " ".join("".join(out).split())
