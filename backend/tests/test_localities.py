"""Справочник НП: загрузка data/seed/localities_ru.csv.gz (идемпотентность, привязка демо)
и поиск: префикс > похожесть > население, ё = е, опечатки, тёзки различаются районом."""

import csv
import gzip
import io
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import seed_localities
from app.models.geo import Locality
from app.models.system import AuditLog
from app.services import localities
from tests.factories import make_locality, random_area, shift_north


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=seed_localities.COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode()))
    return path


def _row(key: str, name: str, lat: float, lon: float, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "key": key,
        "name": name,
        "kind": "village",
        "region": "Новгородская область",
        "region_code": "53",
        "municipality": "Новгородский муниципальный округ",
        "lat": lat,
        "lon": lon,
        "population": "",
        "timezone": "Europe/Moscow",
    }
    row.update(extra)
    return row


async def _dataset(session: AsyncSession, tmp_path: Path) -> tuple[float, float]:
    lat, lon = random_area()
    tag = f"{lat:.5f}-{lon:.5f}"
    rows = [
        _row(f"t-{tag}-1", "Панковка", lat, lon, kind="pgt", population=9515),
        _row(f"t-{tag}-2", "Пантелеево", *shift_north(lat, lon, 30), population=40),
        _row(f"t-{tag}-3", "Лопанка", *shift_north(lat, lon, 60), population=900),
        _row(f"t-{tag}-4", "Ёлкино", *shift_north(lat, lon, 90), municipality="Шимский район"),
        _row(
            f"t-{tag}-5",
            "Ёлкино",
            *shift_north(lat, lon, 120),
            region="Пермский край",
            region_code="59",
            municipality="Чусовской городской округ",
            timezone="Asia/Yekaterinburg",
        ),
        _row(f"t-{tag}-6", "Усть-Кут", *shift_north(lat, lon, 150), kind="town"),
    ]
    await seed_localities.load(session, _write(tmp_path / "loc.csv.gz", rows))
    await session.commit()
    return lat, lon


async def test_search_exact_prefix_typo_yo(db_session: AsyncSession, tmp_path: Path) -> None:
    await _dataset(db_session, tmp_path)

    exact = await localities.search(db_session, "Панковка")
    assert exact[0].name == "Панковка"

    # «пан»: сначала начинающиеся на «пан» (крупнее — выше), «Лопанка» — ниже префиксных.
    names = [r.name for r in await localities.search(db_session, "пан")]
    assert names.index("Панковка") < names.index("Пантелеево")
    assert "Лопанка" not in names or names.index("Лопанка") > names.index("Пантелеево")

    typo = [r.name for r in await localities.search(db_session, "Понковка")]
    assert "Панковка" in typo

    # ё и е, регистр, дефис и пробел — одно и то же.
    for query in ("Елкино", "ёлкино", "ЕЛКИНО"):
        found = [r for r in await localities.search(db_session, query) if r.name == "Ёлкино"]
        assert len(found) >= 2, query
    assert (await localities.search(db_session, "усть кут"))[0].name == "Усть-Кут"
    assert await localities.search(db_session, "п") == []


async def test_search_homonyms_differ_by_district(
    db_session: AsyncSession, db_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    await _dataset(db_session, tmp_path)
    resp = await db_client.get("/api/v1/localities", params={"q": "Ёлкино", "limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) <= 10
    places = {
        (r["region"], r["municipality"], r["timezone"]) for r in body if r["name"] == "Ёлкино"
    }
    assert ("Новгородская область", "Шимский район", "Europe/Moscow") in places
    assert ("Пермский край", "Чусовской городской округ", "Asia/Yekaterinburg") in places


async def test_import_idempotent_and_links_demo(db_session: AsyncSession, tmp_path: Path) -> None:
    lat, lon = random_area()
    # Демо-НП без key: координаты неточны на 12 км, имя в справочнике длиннее.
    demo = await make_locality(db_session, "Сосновка", lat, lon)
    short = await make_locality(db_session, "Ростов", *shift_north(lat, lon, 200))
    await db_session.commit()
    tag = f"{lat:.5f}-{lon:.5f}"
    path = _write(
        tmp_path / "loc.csv.gz",
        [
            _row(f"i-{tag}-1", "Сосновка", *shift_north(lat, lon, 12), population=300),
            _row(f"i-{tag}-2", "Сосновка", *shift_north(lat, lon, 40)),
            _row(f"i-{tag}-3", "Ростов Великий", *shift_north(lat, lon, 200.5), kind="town"),
        ],
    )

    first = await seed_localities.load(db_session, path)
    await db_session.commit()
    assert first == {"rows": 3, "linked": 2, "created": 1, "updated": 2}
    await db_session.refresh(demo)
    await db_session.refresh(short)
    assert demo.key == f"i-{tag}-1" and demo.population == 300 and demo.source == "osm"
    assert short.key == f"i-{tag}-3" and short.name == "Ростов Великий"

    # Повтор: тот же файл пропускается; принудительно — ничего не меняется.
    assert (await seed_localities.load(db_session, path))["rows"] == 0
    forced = await seed_localities.load(db_session, path, force=True)
    await db_session.commit()
    assert forced == {"rows": 3, "linked": 0, "created": 0, "updated": 0}
    count = await db_session.scalar(
        select(func.count()).select_from(Locality).where(Locality.key.like(f"i-{tag}-%"))
    )
    assert count == 3

    audited = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity_type == "locality", AuditLog.entity_id == demo.id)
    )
    assert audited == 1


async def test_nearest_by_postgis(db_session: AsyncSession, tmp_path: Path) -> None:
    lat, lon = await _dataset(db_session, tmp_path)
    near = await localities.nearest(db_session, *shift_north(lat, lon, 2), limit=3)
    assert near[0].name == "Панковка" and 1.5 < (near[0].distance_km or 0) < 2.5


def test_normalize_matches_db_column() -> None:
    assert localities.normalize("  Ёлкино-Усть  Кут ") == "елкино усть кут"
