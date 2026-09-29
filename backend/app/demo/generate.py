"""Генератор демо-событий «здесь и сейчас» (≈400 событий на 3–4 недели вперёд).

Площадки и населённые пункты — реальные (data/seed/*.json), события вымышлены и в ленте
помечены «Демо-данные». Генерация детерминирована (Random(SEED)): один и тот же набор
ключей и текстов при каждом запуске; даты хранятся относительно дня загрузки (`day`),
поэтому повторный `make seed` сдвигает сеансы к текущей дате.
"""

import random
from itertools import chain
from typing import Any

from app.demo.templates import (
    CITY_COMMUNITY,
    CITY_OFFICIAL,
    COMMUNITY,
    OFFICIAL,
    PRICES,
    Template,
)

SEED = 42
TARGET_EVENTS = 400
HORIZON_DAYS = 27  # сеансы — от сегодня до +4 недель
OFFICIAL_PER_ORG = (5, 8)
UNVERIFIED_PER_ORG = 2

# Крупные города — отдельный слой со своим seed, чтобы не сдвигать основной набор.
# Первые сеансы обеих лент покрывают сегодня…+6 (значит, и ближайшие выходные при любом
# дне загрузки) и вторую неделю.
CITY_SEED = 2026
CITY_HORIZON_DAYS = 13
CITY_OFFICIAL_DAYS = (0, 1, 2, 3, 4, 5, 6, 9, 12)
CITY_COMMUNITY_DAYS = (0, 1, 2, 3, 4, 5, 6, 8, 11)
PUSHKIN_CATEGORIES = {"theatre", "concert", "exhibition", "excursion", "lecture", "masterclass"}


def pick_day(rng: random.Random) -> int:
    """Ближайшие дни гуще: сегодня-завтра и выходные должны быть непустыми."""
    roll = rng.random()
    if roll < 0.12:
        return 0
    if roll < 0.3:
        return rng.randint(1, 2)
    if roll < 0.6:
        return rng.randint(3, 7)
    return rng.randint(8, HORIZON_DAYS)


def sessions_for(rng: random.Random, tpl: Template) -> list[dict[str, Any]]:
    first = pick_day(rng)
    later = (min(first + rng.randint(1, 10), HORIZON_DAYS) for _ in range(tpl.sessions - 1))
    days = sorted({first, *later})
    return [
        {"day": day, "time": rng.choice(tpl.times), "duration_min": tpl.minutes} for day in days
    ]


def price_fields(rng: random.Random, tpl: Template) -> dict[str, Any]:
    price_type, mins, maxs = PRICES[tpl.price]
    price_min = rng.choice(mins) if mins else None
    price_max = rng.choice(maxs) if maxs else None
    return {"price_type": price_type, "price_min": price_min, "price_max": price_max}


def _event_dict(
    key: str,
    tpl: Template,
    locality: str,
    venue: str | None,
    *,
    official: bool,
    prices: dict[str, Any],
    pushkin: bool,
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": tpl.title,
        "short_description": tpl.short,
        "description": tpl.description,
        "category": tpl.category,
        "tags": list(tpl.tags),
        "locality": locality,
        "venue": venue,
        "organizer": "venue" if official else None,
        **prices,
        "pushkin_card": pushkin,
        "age_rating": tpl.age,
        "indoor": tpl.indoor,
        "registration_required": tpl.registration,
        "sessions": sessions,
    }


def build_event(
    rng: random.Random, key: str, tpl: Template, locality: str, venue: str | None, *, official: bool
) -> dict[str, Any]:
    prices = price_fields(rng, tpl)
    pushkin = official and prices["price_type"] == "paid" and rng.random() < 0.5
    return _event_dict(
        key,
        tpl,
        locality,
        venue,
        official=official,
        prices=prices,
        pushkin=pushkin,
        sessions=sessions_for(rng, tpl),
    )


def build_events(
    localities: list[dict[str, Any]], venues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """События в формате EventSeed (app.seed). Официальные — только от проверенных организаций."""
    rng = random.Random(SEED)  # noqa: S311 — нужна воспроизводимость, не криптостойкость
    region_of = {loc["key"]: loc["region_code"] for loc in localities}
    events: list[dict[str, Any]] = []

    def add(tpl: Template, locality: str, venue: str | None, *, official: bool) -> None:
        key = f"demo-{len(events) + 1:03d}"
        events.append(build_event(rng, key, tpl, locality, venue, official=official))

    def fits(tpl: Template, venue: dict[str, Any], kind: str) -> bool:
        return (
            kind in tpl.kinds
            and (not tpl.only_venues or venue["key"] in tpl.only_venues)
            and tpl.region in (None, region_of[venue["locality"]])
        )

    # Официальные: от проверенных учреждений.
    for venue in venues:
        if venue.get("org_kind") is None or not venue.get("verified", True):
            continue
        fitting = [t for t in OFFICIAL if fits(t, venue, venue["org_kind"])]
        count = rng.randint(*OFFICIAL_PER_ORG)
        for tpl in rng.sample(fitting, min(count, len(fitting))):
            add(tpl, venue["locality"], venue["key"], official=True)

    # Организация ещё не проверена — её события идут в ленту сообщества.
    for venue in venues:
        if venue.get("org_kind") is None or venue.get("verified", True):
            continue
        fitting = [t for t in COMMUNITY if fits(t, venue, venue["org_kind"])] or COMMUNITY
        for tpl in rng.sample(fitting, min(UNVERIFIED_PER_ORG, len(fitting))):
            add(tpl, venue["locality"], venue["key"], official=False)

    # От жителей: жители и клубы на открытых площадках, в ДК или без площадки.
    open_venues = [v for v in venues if v.get("org_kind") is None]
    dk_venues = [v for v in venues if v.get("org_kind") == "dk" or "Дом культуры" in v["name"]]
    places = [loc["key"] for loc in localities]
    i = 0
    while len(events) < TARGET_EVENTS:
        tpl = COMMUNITY[i % len(COMMUNITY)]
        i += 1
        where = rng.choice(tpl.kinds)
        if where == "open":
            venue = rng.choice(open_venues)
        elif where == "dk":
            venue = rng.choice(dk_venues)
        else:
            add(tpl, rng.choice(places), None, official=False)
            continue
        add(tpl, venue["locality"], venue["key"], official=False)
    return events


def city_sessions(rng: random.Random, tpl: Template, first: int) -> list[dict[str, Any]]:
    """Повторы — через неделю. Сегодня — самый поздний сеанс, чтобы он не успел пройти."""
    days = sorted({min(first + 7 * n, CITY_HORIZON_DAYS) for n in range(tpl.sessions)})
    return [
        {
            "day": day,
            "time": tpl.times[-1] if day == 0 else rng.choice(tpl.times),
            "duration_min": tpl.minutes,
        }
        for day in days
    ]


def build_city_events() -> list[dict[str, Any]]:
    """Демо-афиша Казани и Москвы: official — от проверенных учреждений, community — от жителей."""
    rng = random.Random(CITY_SEED)  # noqa: S311 — нужна воспроизводимость, не криптостойкость
    events: list[dict[str, Any]] = []
    for city, official in CITY_OFFICIAL.items():
        plan = chain(
            ((tpl, day, True) for tpl, day in zip(official, CITY_OFFICIAL_DAYS, strict=True)),
            (
                (tpl, day, False)
                for tpl, day in zip(CITY_COMMUNITY[city], CITY_COMMUNITY_DAYS, strict=True)
            ),
        )
        for n, (tpl, day, is_official) in enumerate(plan, 1):
            prices = price_fields(rng, tpl)
            pushkin = (
                is_official
                and prices["price_type"] == "paid"
                and tpl.category in PUSHKIN_CATEGORIES
            )
            events.append(
                _event_dict(
                    f"demo-{city}-{n:02d}",
                    tpl,
                    city,
                    tpl.only_venues[0] if tpl.only_venues else None,
                    official=is_official,
                    prices=prices,
                    pushkin=pushkin,
                    sessions=city_sessions(rng, tpl, day),
                )
            )
    return events
