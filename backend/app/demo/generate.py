"""Генератор демо-событий «здесь и сейчас» (≈400 событий на 3–4 недели вперёд).

Площадки и населённые пункты — реальные (data/seed/*.json), события вымышлены и в ленте
помечены «Демо-данные». Генерация детерминирована (Random(SEED)): один и тот же набор
ключей и текстов при каждом запуске; даты хранятся относительно дня загрузки (`day`),
поэтому повторный `make seed` сдвигает сеансы к текущей дате.
"""

import random
from typing import Any

from app.demo.templates import COMMUNITY, OFFICIAL, PRICES, Template

SEED = 42
TARGET_EVENTS = 400
HORIZON_DAYS = 27  # сеансы — от сегодня до +4 недель
OFFICIAL_PER_ORG = (5, 8)
UNVERIFIED_PER_ORG = 2


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


def build_event(
    rng: random.Random, key: str, tpl: Template, locality: str, venue: str | None, *, official: bool
) -> dict[str, Any]:
    prices = price_fields(rng, tpl)
    pushkin = official and prices["price_type"] == "paid" and rng.random() < 0.5
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
        "sessions": sessions_for(rng, tpl),
    }


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
