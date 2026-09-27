"""Синхронные правила модерации §6 (< 50 мс): длины, стоп-слова, ссылки, контакты, даты, цена.

Нарушения двух видов:
- form — ошибка заполнения: форма показывает её пользователю, статус не меняется;
- content — нарушение правил площадки: событие отклоняется с причиной.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

STOPWORDS_FILE = Path(__file__).resolve().parent / "stopwords.txt"

TITLE_MAX = 120
DESCRIPTION_MAX = 4000
TAGS_MAX = 5
SESSIONS_MAX = 20
HORIZON = timedelta(days=365)

URL_SHORTENERS = frozenset(
    {
        "bit.ly",
        "clck.ru",
        "tinyurl.com",
        "goo.gl",
        "t.co",
        "cutt.ly",
        "vk.cc",
        "is.gd",
        "ow.ly",
        "u.to",
        "qps.ru",
        "rebrand.ly",
        "shorturl.at",
        "tiny.cc",
    }
)
BLOCKED_DOMAINS = frozenset({"grabify.link", "iplogger.org", "iplogger.com", "2no.co"})

_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')]+", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

Kind = Literal["form", "content"]


@dataclass(frozen=True)
class Violation:
    code: str
    field: str
    message: str
    kind: Kind = "form"


@dataclass
class SessionData:
    starts_at: datetime
    ends_at: datetime | None
    is_new: bool = True


@dataclass
class EventData:
    title: str
    description: str | None = None
    short_description: str | None = None
    tags: list[str] = field(default_factory=list)
    contacts: str | None = None
    links: list[str] = field(default_factory=list)
    sessions: list[SessionData] = field(default_factory=list)
    price_min: Decimal | None = None
    price_max: Decimal | None = None


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


@cache
def stopwords() -> tuple[str, ...]:
    lines = STOPWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return tuple(_normalize(s.strip()) for s in lines if s.strip() and not s.startswith("#"))


def _host(url: str) -> str:
    raw = url if "://" in url else f"https://{url}"
    host = (urlsplit(raw).hostname or "").lower()
    return host.removeprefix("www.")


def _check_link(url: str, field_name: str) -> Violation | None:
    host = _host(url)
    if host in URL_SHORTENERS:
        return Violation(
            "url_shortener", field_name, f"Сокращённые ссылки запрещены: {host}", "content"
        )
    if host in BLOCKED_DOMAINS or any(host.endswith("." + d) for d in BLOCKED_DOMAINS):
        return Violation("blocked_domain", field_name, f"Домен {host} запрещён", "content")
    if not url.lower().startswith("https://") and not url.lower().startswith("www."):
        return Violation("insecure_url", field_name, "Ссылки только https://", "content")
    return None


def check(data: EventData, now: datetime) -> list[Violation]:
    found: list[Violation] = []
    if not data.title.strip():
        found.append(Violation("required", "title", "Укажи название"))
    if len(data.title) > TITLE_MAX:
        found.append(Violation("too_long", "title", f"Название — до {TITLE_MAX} символов"))
    if data.description and len(data.description) > DESCRIPTION_MAX:
        found.append(
            Violation("too_long", "description", f"Описание — до {DESCRIPTION_MAX} символов")
        )
    if len(data.tags) > TAGS_MAX:
        found.append(Violation("too_many", "tags", f"Не больше {TAGS_MAX} тегов"))

    # Даты: сеансы в будущем и не дальше года.
    if not data.sessions:
        found.append(Violation("required", "sessions", "Добавь хотя бы один сеанс"))
    if len(data.sessions) > SESSIONS_MAX:
        found.append(Violation("too_many", "sessions", f"Не больше {SESSIONS_MAX} сеансов"))
    for s in data.sessions:
        if s.is_new and s.starts_at <= now:
            found.append(Violation("past_date", "sessions", "Дата сеанса уже прошла"))
            break
        if s.starts_at > now + HORIZON:
            found.append(Violation("far_date", "sessions", "Сеанс — не дальше чем через год"))
            break
        if s.ends_at is not None and s.ends_at < s.starts_at:
            found.append(Violation("bad_range", "sessions", "Окончание раньше начала"))
            break
    if data.sessions and all((s.ends_at or s.starts_at) <= now for s in data.sessions):
        found.append(Violation("past_date", "sessions", "Нужен хотя бы один будущий сеанс"))

    # Цена.
    for name, value in (("price_min", data.price_min), ("price_max", data.price_max)):
        if value is not None and value < 0:
            found.append(Violation("negative_price", name, "Цена не может быть меньше нуля"))
    if (
        data.price_min is not None
        and data.price_max is not None
        and data.price_max < data.price_min
    ):
        found.append(Violation("bad_range", "price_max", "Цена «до» меньше цены «от»"))

    # Текст: стоп-слова, ссылки, контакты вне поля «Контакты».
    texts = {
        "title": data.title,
        "short_description": data.short_description or "",
        "description": data.description or "",
    }
    words = stopwords()
    for name, text in texts.items():
        normalized = _normalize(text)
        hit = next((w for w in words if w in normalized), None)
        if hit is not None:
            found.append(Violation("stopword", name, "Текст нарушает правила площадки", "content"))
            break
    for name, text in texts.items():
        if _PHONE.search(text) or _EMAIL.search(text):
            found.append(
                Violation(
                    "contacts_in_text",
                    name,
                    "Телефон и почту укажи в поле «Контакты», не в тексте",
                    "content",
                )
            )
            break
    for name, text in texts.items():
        for url in _URL.findall(text):
            violation = _check_link(url, name)
            if violation is not None:
                found.append(violation)
                break
    for url in data.links:
        violation = _check_link(url, "links")
        if violation is not None:
            found.append(violation)
    return found


def content_reason(violations: list[Violation]) -> str:
    return "; ".join(dict.fromkeys(v.message for v in violations if v.kind == "content"))


# --- Оценка подозрительности (сообщество) ---------------------------------------------
# Чистое событие публикуется сразу, подозрительное ждёт администратора с причинами.

SUSPICIOUS_SCORE = 2
CAPS_MIN_LETTERS = 8
CAPS_SHARE = 0.7
DESCRIPTION_MIN = 30
AD_WORDS = (
    "заработ",
    "кредит",
    "займ",
    "казино",
    "ставк",
    "букмекер",
    "промокод",
    "скидк",
    "распродаж",
    "подпишись",
    "подписывайтесь",
    "розыгрыш",
    "только сегодня",
    "криптовалют",
    "инвестиц",
)
_REPEAT_CHAR = re.compile(r"(\w)\1{4,}")
_EXCLAIM = re.compile(r"[!?]{3,}")
_WORD = re.compile(r"[а-яёa-z]{3,}", re.I)


def _caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= CAPS_MIN_LETTERS and (
        sum(c.isupper() for c in letters) / len(letters) >= CAPS_SHARE
    )


def _repeated_words(text: str) -> bool:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 6:
        return False
    top = max(words.count(w) for w in set(words))
    return top >= 4 and top / len(words) >= 0.25


def score(data: EventData) -> tuple[int, list[str]]:
    """Баллы подозрительности и причины для администратора."""
    found: list[tuple[int, str]] = []
    text = "\n".join(p for p in (data.title, data.short_description, data.description) if p)
    if _caps(data.title):
        found.append((2, "название заглавными буквами"))
    if _REPEAT_CHAR.search(text) or _EXCLAIM.search(text):
        found.append((1, "повторы символов"))
    if _repeated_words(text):
        found.append((1, "повторы слов"))
    normalized = _normalize(text)
    if any(w in normalized for w in AD_WORDS):
        found.append((2, "похоже на рекламу"))
    if len((data.description or data.short_description or "").strip()) < DESCRIPTION_MIN:
        found.append((1, "мало информации о событии"))
    return sum(p for p, _ in found), [r for _, r in found]
