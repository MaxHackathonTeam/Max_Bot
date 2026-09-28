"""Справочник населённых пунктов России: data/seed/localities_ru.csv.gz → таблица localities.

Файл собирает tools/build_localities.py из OpenStreetMap (© участники OpenStreetMap, ODbL).
Загрузка идемпотентна и запускается из `python -m app.seed` при каждом старте migrate:
  1. если файл с тем же sha256 уже загружен (запись locality.import в audit_log) — пропуск;
  2. COPY во временную таблицу;
  3. пункты без key (демо-набор, созданные вручную) привязываются к строке справочника
     с тем же именем поблизости (SAME_NAME_M) — их связи с площадками и событиями сохраняются;
  4. upsert по key; меняются только строки, где что-то отличается.
Каждое созданное и изменённое НП пишется в audit_log (audit.record_many).
"""

import asyncio
import csv
import gzip
import hashlib
import io
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditActor
from app.services import audit
from app.services.localities import SAME_NAME_M

FILE_NAME = "localities_ru.csv.gz"
SOURCE = "osm"
IMPORT_ACTION = "locality.import"
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

log = structlog.get_logger(__name__)

_STAGE_DDL = """
CREATE TEMP TABLE stage_localities (
    key varchar(64) PRIMARY KEY,
    name varchar(255) NOT NULL,
    kind varchar(16) NOT NULL,
    region varchar(255),
    region_code varchar(8),
    municipality varchar(255),
    lat float8 NOT NULL,
    lon float8 NOT NULL,
    population integer,
    timezone varchar(64) NOT NULL
) ON COMMIT DROP
"""

# Пункту без key — ближайшая строка справочника с тем же именем (или «имя …») в радиусе
# SAME_NAME_M, точное имя важнее расстояния; одна строка справочника — одному пункту.
_LINK_SQL = """
WITH stage AS (
    SELECT key, translate(lower(name), 'ё-–', 'е  ') AS name_norm,
           ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS point
    FROM stage_localities
), cand AS (
    SELECT DISTINCT ON (l.id) l.id, s.key, s.name_norm = l.name_norm AS exact,
           ST_Distance(l.point, s.point) AS dist
    FROM localities l
    JOIN stage s ON s.name_norm = l.name_norm OR s.name_norm LIKE l.name_norm || ' %'
    WHERE l.key IS NULL
      AND ST_DWithin(l.point, s.point, :radius)
      AND NOT EXISTS (SELECT 1 FROM localities k WHERE k.key = s.key)
    ORDER BY l.id, exact DESC, dist
), uniq AS (
    SELECT DISTINCT ON (key) id, key FROM cand ORDER BY key, exact DESC, dist, id
)
UPDATE localities SET key = uniq.key FROM uniq WHERE localities.id = uniq.id
RETURNING localities.id
"""

_UPSERT_SQL = """
INSERT INTO localities
    (key, name, kind, region, region_code, municipality, point, timezone, population, source)
SELECT key, name, kind, region, region_code, municipality,
       ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography, timezone, population, :source
FROM stage_localities
ON CONFLICT (key) DO UPDATE SET
    name = EXCLUDED.name,
    kind = EXCLUDED.kind,
    region = EXCLUDED.region,
    region_code = EXCLUDED.region_code,
    municipality = EXCLUDED.municipality,
    point = EXCLUDED.point,
    timezone = EXCLUDED.timezone,
    population = EXCLUDED.population,
    source = EXCLUDED.source,
    updated_at = now()
WHERE (localities.name, localities.kind, localities.region, localities.region_code,
       localities.municipality, localities.timezone, localities.population, localities.source,
       ST_X(localities.point::geometry), ST_Y(localities.point::geometry))
  IS DISTINCT FROM
      (EXCLUDED.name, EXCLUDED.kind, EXCLUDED.region, EXCLUDED.region_code,
       EXCLUDED.municipality, EXCLUDED.timezone, EXCLUDED.population, EXCLUDED.source,
       ST_X(EXCLUDED.point::geometry), ST_Y(EXCLUDED.point::geometry))
RETURNING id, (xmax = 0) AS created
"""


def read_rows(raw: bytes) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    with io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{FILE_NAME}: ожидаются колонки {','.join(COLUMNS)}")
        for r in reader:
            rows.append(
                (
                    r["key"],
                    r["name"],
                    r["kind"],
                    r["region"] or None,
                    r["region_code"] or None,
                    r["municipality"] or None,
                    float(r["lat"]),
                    float(r["lon"]),
                    int(r["population"]) if r["population"] else None,
                    r["timezone"],
                )
            )
    return rows


async def _loaded_sha(session: AsyncSession) -> str | None:
    value = await session.scalar(
        text(
            "SELECT diff->>'sha256' FROM audit_log WHERE action = :action ORDER BY id DESC LIMIT 1"
        ),
        {"action": IMPORT_ACTION},
    )
    return str(value) if value is not None else None


async def load(session: AsyncSession, path: Path, *, force: bool = False) -> dict[str, int]:
    """Загружает справочник в текущей транзакции (commit — на вызывающем)."""
    raw = await asyncio.to_thread(path.read_bytes)
    sha = hashlib.sha256(raw).hexdigest()
    if not force and await _loaded_sha(session) == sha:
        log.info("localities_import_skipped", reason="тот же файл уже загружен")
        return {"rows": 0, "linked": 0, "created": 0, "updated": 0}
    rows = read_rows(raw)

    await session.execute(text(_STAGE_DDL))
    conn = await session.connection()
    raw_conn = await conn.get_raw_connection()
    await raw_conn.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
        "stage_localities", records=rows, columns=list(COLUMNS)
    )

    linked = [r[0] for r in (await session.execute(text(_LINK_SQL), {"radius": SAME_NAME_M})).all()]
    result = (await session.execute(text(_UPSERT_SQL), {"source": SOURCE})).all()
    created = [r[0] for r in result if r[1]]
    updated = [r[0] for r in result if not r[1]]

    for action, ids in (("locality.create", created), ("locality.update", updated)):
        await audit.record_many(
            session,
            action=action,
            entity_type="locality",
            entity_ids=ids,
            diff={"source": SOURCE, "file": FILE_NAME},
        )
    stats = {
        "rows": len(rows),
        "linked": len(linked),
        "created": len(created),
        "updated": len(updated),
    }
    await audit.record(
        session,
        action=IMPORT_ACTION,
        entity_type="locality",
        entity_id=None,
        actor_type=AuditActor.system,
        diff={"sha256": sha, "file": FILE_NAME, **stats},
    )
    log.info("localities_imported", **stats)
    return stats
