# /// script
# requires-python = ">=3.12"
# dependencies = ["osmium==4.3.1", "shapely==2.1.2"]
# ///
"""Сборка справочника населённых пунктов России из OpenStreetMap (ODbL 1.0).

Запускает человек, раз в полгода; в рантайме сервис никуда не ходит — `make seed`
читает только результат data/seed/localities_ru.csv.gz.

    curl -L -o /tmp/russia-latest.osm.pbf https://download.geofabrik.de/russia-latest.osm.pbf
    uv run tools/build_localities.py /tmp/russia-latest.osm.pbf data/seed/localities_ru.csv.gz

Что берём: узлы place=city|town|village|hamlet с русским названием. Субъект и район —
по вхождению точки в границы admin_level=4 и admin_level=6. Часовой пояс — по субъекту
из таблицы REGIONS (детерминированно, без геокодеров). Выход детерминирован:
строки отсортированы, gzip без имени файла и времени.

© участники OpenStreetMap, данные доступны по лицензии ODbL 1.0 (openstreetmap.org/copyright).
"""

import csv
import gzip
import io
import re
import sys
import time
from pathlib import Path

import osmium
import shapely
from shapely import wkb
from shapely.strtree import STRtree

PLACES = {"city", "town", "village", "hamlet"}
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
COLUMNS = (
    "key",
    "name",
    "kind",
    "region",
    "region_code",
    "municipality",
    "lat",
    "lon",
    "population",
    "timezone",
)

# ISO 3166-2 → (код субъекта, часовой пояс). Для субъектов с несколькими поясами
# берётся пояс столицы (Якутия — Asia/Yakutsk, Сахалинская — Asia/Sakhalin).
REGIONS: dict[str, tuple[str, str]] = {
    "RU-AD": ("01", "Europe/Moscow"),
    "RU-BA": ("02", "Asia/Yekaterinburg"),
    "RU-BU": ("03", "Asia/Irkutsk"),
    "RU-AL": ("04", "Asia/Barnaul"),
    "RU-DA": ("05", "Europe/Moscow"),
    "RU-IN": ("06", "Europe/Moscow"),
    "RU-KB": ("07", "Europe/Moscow"),
    "RU-KL": ("08", "Europe/Moscow"),
    "RU-KC": ("09", "Europe/Moscow"),
    "RU-KR": ("10", "Europe/Moscow"),
    "RU-KO": ("11", "Europe/Moscow"),
    "RU-ME": ("12", "Europe/Moscow"),
    "RU-MO": ("13", "Europe/Moscow"),
    "RU-SA": ("14", "Asia/Yakutsk"),
    "RU-SE": ("15", "Europe/Moscow"),
    "RU-TA": ("16", "Europe/Moscow"),
    "RU-TY": ("17", "Asia/Krasnoyarsk"),
    "RU-UD": ("18", "Europe/Samara"),
    "RU-KK": ("19", "Asia/Krasnoyarsk"),
    "RU-CE": ("20", "Europe/Moscow"),
    "RU-CU": ("21", "Europe/Moscow"),
    "RU-ALT": ("22", "Asia/Barnaul"),
    "RU-KDA": ("23", "Europe/Moscow"),
    "RU-KYA": ("24", "Asia/Krasnoyarsk"),
    "RU-PRI": ("25", "Asia/Vladivostok"),
    "RU-STA": ("26", "Europe/Moscow"),
    "RU-KHA": ("27", "Asia/Vladivostok"),
    "RU-AMU": ("28", "Asia/Yakutsk"),
    "RU-ARK": ("29", "Europe/Moscow"),
    "RU-AST": ("30", "Europe/Astrakhan"),
    "RU-BEL": ("31", "Europe/Moscow"),
    "RU-BRY": ("32", "Europe/Moscow"),
    "RU-VLA": ("33", "Europe/Moscow"),
    "RU-VGG": ("34", "Europe/Volgograd"),
    "RU-VLG": ("35", "Europe/Moscow"),
    "RU-VOR": ("36", "Europe/Moscow"),
    "RU-IVA": ("37", "Europe/Moscow"),
    "RU-IRK": ("38", "Asia/Irkutsk"),
    "RU-KGD": ("39", "Europe/Kaliningrad"),
    "RU-KLU": ("40", "Europe/Moscow"),
    "RU-KAM": ("41", "Asia/Kamchatka"),
    "RU-KEM": ("42", "Asia/Novokuznetsk"),
    "RU-KIR": ("43", "Europe/Kirov"),
    "RU-KOS": ("44", "Europe/Moscow"),
    "RU-KGN": ("45", "Asia/Yekaterinburg"),
    "RU-KRS": ("46", "Europe/Moscow"),
    "RU-LEN": ("47", "Europe/Moscow"),
    "RU-LIP": ("48", "Europe/Moscow"),
    "RU-MAG": ("49", "Asia/Magadan"),
    "RU-MOS": ("50", "Europe/Moscow"),
    "RU-MUR": ("51", "Europe/Moscow"),
    "RU-NIZ": ("52", "Europe/Moscow"),
    "RU-NGR": ("53", "Europe/Moscow"),
    "RU-NVS": ("54", "Asia/Novosibirsk"),
    "RU-OMS": ("55", "Asia/Omsk"),
    "RU-ORE": ("56", "Asia/Yekaterinburg"),
    "RU-ORL": ("57", "Europe/Moscow"),
    "RU-PNZ": ("58", "Europe/Moscow"),
    "RU-PER": ("59", "Asia/Yekaterinburg"),
    "RU-PSK": ("60", "Europe/Moscow"),
    "RU-ROS": ("61", "Europe/Moscow"),
    "RU-RYA": ("62", "Europe/Moscow"),
    "RU-SAM": ("63", "Europe/Samara"),
    "RU-SAR": ("64", "Europe/Saratov"),
    "RU-SAK": ("65", "Asia/Sakhalin"),
    "RU-SVE": ("66", "Asia/Yekaterinburg"),
    "RU-SMO": ("67", "Europe/Moscow"),
    "RU-TAM": ("68", "Europe/Moscow"),
    "RU-TVE": ("69", "Europe/Moscow"),
    "RU-TOM": ("70", "Asia/Tomsk"),
    "RU-TUL": ("71", "Europe/Moscow"),
    "RU-TYU": ("72", "Asia/Yekaterinburg"),
    "RU-ULY": ("73", "Europe/Ulyanovsk"),
    "RU-CHE": ("74", "Asia/Yekaterinburg"),
    "RU-ZAB": ("75", "Asia/Chita"),
    "RU-YAR": ("76", "Europe/Moscow"),
    "RU-MOW": ("77", "Europe/Moscow"),
    "RU-SPE": ("78", "Europe/Moscow"),
    "RU-YEV": ("79", "Asia/Vladivostok"),
    "RU-NEN": ("83", "Europe/Moscow"),
    "RU-KHM": ("86", "Asia/Yekaterinburg"),
    "RU-CHU": ("87", "Asia/Anadyr"),
    "RU-YAN": ("89", "Asia/Yekaterinburg"),
}
# Субъекты, у которых в OSM нет ISO3166-2 RU-*: берём по названию, коды — как в ФИАС.
# Одноимённые отношения с ISO UA-* пропускаются (иначе точки попадут в два субъекта).
REGIONS_BY_NAME: dict[str, tuple[str, str]] = {
    "Республика Крым": ("91", "Europe/Simferopol"),
    "Севастополь": ("92", "Europe/Simferopol"),
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def kind_of(place: str, status: str) -> str:
    status = status.lower()
    if "городского типа" in status or "рабочий" in status or "курортный" in status:
        return "pgt"
    if place == "city":
        return "city"
    if place == "town":
        return "town"
    if "посёлок" in status or "поселок" in status:
        return "settlement"
    return "village"


def population_of(raw: str | None) -> str:
    digits = re.sub(r"\s", "", raw or "")
    return digits if digits.isdigit() else ""


def extract_boundaries(src: Path, dst: Path) -> None:
    """Малый файл: отношения admin_level=4|6 со всеми путями и узлами."""
    admin = osmium.filter.TagFilter(("admin_level", "4"), ("admin_level", "6"))
    with osmium.BackReferenceWriter(str(dst), ref_src=str(src), overwrite=True) as writer:
        for rel in osmium.FileProcessor(str(src), osmium.osm.RELATION).with_filter(admin):
            if rel.tags.get("boundary") == "administrative":
                writer.add_relation(rel)


def read_boundaries(path: Path) -> tuple[list, list]:
    factory = osmium.geom.WKBFactory()
    regions: list = []
    districts: list = []
    for area in (
        osmium.FileProcessor(str(path))
        .with_areas()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA))
    ):
        if area.from_way() or area.tags.get("boundary") != "administrative":
            continue
        level = area.tags.get("admin_level")
        name = area.tags.get("name:ru") or area.tags.get("name")
        if level not in ("4", "6") or not name:
            continue
        try:
            geom = wkb.loads(factory.create_multipolygon(area), hex=True)
        except RuntimeError:
            continue
        if level == "4":
            iso = area.tags.get("ISO3166-2", "")
            code_tz = REGIONS.get(iso) or (None if iso else REGIONS_BY_NAME.get(name))
            if code_tz is not None:
                regions.append((geom, name, *code_tz))
            else:
                log(f"пропущен субъект без кода в таблице: {name} ({iso or 'нет ISO'})")
        else:
            districts.append((geom, name))
    # Порядок областей в файле не гарантирован — сортируем для детерминизма.
    regions.sort(key=lambda r: (r[2], r[1]))
    districts.sort(key=lambda d: (d[1], d[0].centroid.x))
    return regions, districts


def read_places(src: Path) -> list[tuple[int, str, str, float, float, str]]:
    places = []
    for node in osmium.FileProcessor(str(src), osmium.osm.NODE).with_filter(
        osmium.filter.KeyFilter("place")
    ):
        place = node.tags.get("place")
        if place not in PLACES:
            continue
        name = node.tags.get("name:ru") or node.tags.get("name")
        if not name or not CYRILLIC.search(name):
            continue
        status = f"{node.tags.get('official_status', '')} {node.tags.get('ru:official_status', '')}"
        places.append(
            (
                node.id,
                name.strip(),
                kind_of(place, status),
                node.location.lat,
                node.location.lon,
                population_of(node.tags.get("population")),
            )
        )
    return places


def locate(points: list, polygons: list) -> list[int | None]:
    """Индекс полигона, в который попадает каждая точка (первый по порядку)."""
    tree = STRtree([p[0] for p in polygons])
    found: list[int | None] = [None] * len(points)
    point_idx, poly_idx = tree.query(points, predicate="within")
    for i, j in sorted(zip(point_idx.tolist(), poly_idx.tolist(), strict=True)):
        if found[i] is None:
            found[i] = j
    return found


def main(src: Path, out: Path) -> None:
    work = src.with_name("boundaries-4-6.osm.pbf")
    if not work.exists():
        log("вырезаю границы субъектов и районов")
        extract_boundaries(src, work)
    log("собираю полигоны границ")
    regions, districts = read_boundaries(work)
    log(f"субъектов: {len(regions)}, районов: {len(districts)}")
    log("читаю населённые пункты")
    places = read_places(src)
    log(f"узлов place: {len(places)}")
    points = shapely.points([(p[4], p[3]) for p in places])
    region_of = locate(points, regions)
    district_of = locate(points, districts)

    rows = []
    for place, r, d in zip(places, region_of, district_of, strict=True):
        if r is None:
            continue  # за границами субъектов РФ (узлы у границы в выгрузке)
        _, region, code, tz = regions[r]
        municipality = ""
        if d is not None and districts[d][0].representative_point().within(regions[r][0]):
            municipality = districts[d][1]
        osm_id, name, kind, lat, lon, population = place
        rows.append(
            (
                f"osm-n{osm_id}",
                name,
                kind,
                region,
                code,
                municipality,
                f"{lat:.5f}",
                f"{lon:.5f}",
                population,
                tz,
            )
        )
    rows.sort(key=lambda r: (r[4], r[1], r[0]))
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    with (
        out.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz,
    ):
        gz.write(buf.getvalue().encode())
    log(f"записано {len(rows)} строк в {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: build_localities.py <russia.osm.pbf> <out.csv.gz>")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
