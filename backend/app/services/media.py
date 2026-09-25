"""Обложки событий (FR-PUB-1): проверка сигнатуры, перекодирование в WebP без EXIF (§14)."""

import asyncio
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.events import Media
from app.models.users import User
from app.schemas.venues import MediaOut
from app.services import audit

log = structlog.get_logger(__name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000
WEBP_QUALITY = 82
URL_PREFIX = "/media/"

# Защита от «бомб»: Pillow бросит DecompressionBombError выше двойного лимита.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def sniff(data: bytes) -> str | None:
    """Тип по сигнатуре файла, а не по имени и Content-Type клиента."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@dataclass(frozen=True)
class Processed:
    data: bytes
    width: int
    height: int


def process(data: bytes) -> Processed:
    """Поворот по EXIF, уменьшение до 1600 px, WebP без метаданных."""
    kind = sniff(data)
    if kind is None:
        raise AppError("unsupported_media", "Нужна картинка JPG, PNG или WebP", status_code=415)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise AppError("image_too_large", "Слишком большое разрешение картинки", 413)
            image.load()
            oriented = ImageOps.exif_transpose(image)
            oriented.thumbnail((MAX_SIDE, MAX_SIDE))
            if oriented.mode not in ("RGB", "RGBA"):
                oriented = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
            out = io.BytesIO()
            # Новый файл собирается из пикселей: EXIF, XMP и ICC-профиль не переносятся.
            oriented.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)
            return Processed(out.getvalue(), oriented.width, oriented.height)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        log.info("media_decode_failed", error=type(exc).__name__)
        raise AppError("bad_image", "Не получилось открыть картинку", status_code=422) from exc


def media_url(media: Media) -> str:
    return f"{URL_PREFIX}{media.path}"


def to_out(media: Media) -> MediaOut:
    return MediaOut(
        id=media.id, url=media_url(media), width=media.width, height=media.height, size=media.size
    )


async def upload(session: AsyncSession, user: User, data: bytes, media_dir: str) -> Media:
    if not data:
        raise AppError("empty_file", "Файл пустой", status_code=422)
    if len(data) > MAX_BYTES:
        raise AppError("file_too_large", "Картинка больше 5 МБ", status_code=413)
    processed = await asyncio.to_thread(process, data)
    name = f"{uuid.uuid4().hex}.webp"
    directory = Path(media_dir)
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((directory / name).write_bytes, processed.data)
    media = Media(
        owner_user_id=user.id,
        path=name,
        mime="image/webp",
        width=processed.width,
        height=processed.height,
        size=len(processed.data),
        sha256=hashlib.sha256(processed.data).hexdigest(),
    )
    session.add(media)
    await session.flush()
    await audit.record(
        session,
        action="media.upload",
        entity_type="media",
        entity_id=media.id,
        actor_user_id=user.id,
        diff={"size": media.size, "width": media.width, "height": media.height},
    )
    await session.commit()
    return media
