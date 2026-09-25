"""Unit-тесты этапа 3: правила модерации, SSRF-фильтр, подпись контакта, обработка картинок."""

import base64
import hashlib
import hmac
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image

from app.core.errors import AppError
from app.integrations.safe_fetch import (
    FetchError,
    UnsafeUrlError,
    check_url,
    fetch_page,
    html_to_text,
    is_public_ip,
)
from app.moderation import rules
from app.services import media as media_service
from app.services import moderation as moderation_service
from app.services.verification import contact_hash_valid, name_similarity, normalize_name

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _data(**overrides: object) -> rules.EventData:
    base: dict[str, object] = {
        "title": "Концерт хора",
        "description": "Народные песни в сельском клубе",
        "short_description": None,
        "tags": ["хор"],
        "contacts": None,
        "links": [],
        "sessions": [rules.SessionData(NOW + timedelta(days=2), None)],
        "price_min": None,
        "price_max": None,
    }
    base.update(overrides)
    return rules.EventData(**base)  # type: ignore[arg-type]


def _codes(data: rules.EventData) -> set[str]:
    return {v.code for v in rules.check(data, NOW)}


# --- Правила модерации (§6 п. 1) ------------------------------------------------------


def test_rules_clean_event_passes() -> None:
    assert rules.check(_data(), NOW) == []


def test_rules_form_violations() -> None:
    assert "required" in _codes(_data(title=""))
    assert "too_long" in _codes(_data(title="x" * 121))
    assert "required" in _codes(_data(sessions=[]))
    past = [rules.SessionData(NOW - timedelta(hours=1), None)]
    assert "past_date" in _codes(_data(sessions=past))
    far = [rules.SessionData(NOW + timedelta(days=400), None)]
    assert "far_date" in _codes(_data(sessions=far))
    bad_end = [rules.SessionData(NOW + timedelta(days=1), NOW + timedelta(hours=1))]
    assert "bad_range" in _codes(_data(sessions=bad_end))
    assert "bad_range" in _codes(_data(price_min=500, price_max=100))
    assert all(v.kind == "form" for v in rules.check(_data(title=""), NOW))


def test_rules_old_session_is_not_rechecked_on_edit() -> None:
    old = rules.SessionData(NOW - timedelta(hours=1), None, is_new=False)
    future = rules.SessionData(NOW + timedelta(days=1), None)
    assert rules.check(_data(sessions=[old, future]), NOW) == []
    # Совсем без будущих сеансов событие не опубликовать.
    assert "past_date" in _codes(_data(sessions=[old]))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("description", "Лучшее онлайн-КАЗИНО района", "stopword"),
        ("description", "Звоните +7 (912) 345-67-89", "contacts_in_text"),
        ("title", "Пишите на party@example.com", "contacts_in_text"),
        ("links", ["https://bit.ly/abc"], "url_shortener"),
        ("links", ["http://example.ru/tickets"], "insecure_url"),
    ],
)
def test_rules_content_violations(field: str, value: object, code: str) -> None:
    violations = rules.check(_data(**{field: value}), NOW)
    assert code in {v.code for v in violations}
    assert any(v.kind == "content" for v in violations)
    assert rules.content_reason([v for v in violations if v.kind == "content"])


def test_contacts_field_allows_phone() -> None:
    assert rules.check(_data(contacts="+7 912 345-67-89"), NOW) == []


# --- Решение по вердикту LLM (§6 п. 2) -------------------------------------------------


def test_decide_llm_matrix() -> None:
    from app.llm.schemas import ModerationVerdictOut as V

    approve_hi = V(verdict="approve", confidence=0.9)
    approve_lo = V(verdict="approve", confidence=0.5)
    reject_hi = V(verdict="reject", confidence=0.95, categories=["spam"])
    review = V(verdict="review", confidence=0.9)
    assert moderation_service.decide_llm("community", approve_hi) == "published"
    assert moderation_service.decide_llm("community", approve_lo) == "pending"
    assert moderation_service.decide_llm("community", reject_hi) == "rejected"
    assert moderation_service.decide_llm("community", review) == "pending"
    assert moderation_service.decide_llm("community", None) == "pending"
    assert moderation_service.decide_llm("official", approve_lo) == "published"
    assert moderation_service.decide_llm("official", reject_hi) == "hidden"
    assert moderation_service.decide_llm("official", None) == "hidden"


def test_retry_delay_stops_after_six_hours() -> None:
    delays = []
    attempt = 0
    while (delay := moderation_service.retry_delay(attempt)) is not None:
        delays.append(delay)
        attempt += 1
    assert delays[0] == 300
    assert sum(delays) <= 6 * 3600
    assert len(delays) >= 3


# --- SSRF-фильтр (§14) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.10", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::1", False),
        ("::ffff:127.0.0.1", False),
        ("fd00::1", False),
        ("0.0.0.0", False),  # noqa: S104 — проверяемое значение
        ("not-an-ip", False),
    ],
)
def test_is_public_ip(ip: str, public: bool) -> None:
    assert is_public_ip(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "http://example.ru/",
        "ftp://example.ru/",
        "https://user:pass@example.ru/",
        "https://example.ru:8443/",
        "https:///nohost",
    ],
)
def test_check_url_rejects(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        check_url(url)


def test_check_url_accepts_https() -> None:
    assert check_url("https://Example.RU/a?b=1") == ("example.ru", "/a?b=1")


def _resolver(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str) -> list[str]:
        return mapping[host]

    return resolve


async def test_fetch_blocks_private_dns() -> None:
    with pytest.raises(UnsafeUrlError):
        await fetch_page("https://evil.test/", resolver=_resolver({"evil.test": ["10.0.0.5"]}))


async def test_fetch_blocks_mixed_dns() -> None:
    resolver = _resolver({"evil.test": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(UnsafeUrlError):
        await fetch_page("https://evil.test/", resolver=resolver)


async def test_fetch_blocks_redirect_to_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://internal.test/admin"})

    resolver = _resolver({"site.test": ["93.184.216.34"], "internal.test": ["192.168.1.1"]})
    with pytest.raises(UnsafeUrlError):
        await fetch_page(
            "https://site.test/", resolver=resolver, transport=httpx.MockTransport(handler)
        )


async def test_fetch_connects_to_checked_ip_with_host_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html="<p>Код AFISHA-ABC123</p><script>x()</script>")

    page = await fetch_page(
        "https://site.test/about",
        resolver=_resolver({"site.test": ["93.184.216.34"]}),
        transport=httpx.MockTransport(handler),
    )
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "site.test"
    assert page.text == "Код AFISHA-ABC123"


async def test_fetch_limits_size_and_status() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 10))

    resolver = _resolver({"site.test": ["93.184.216.34"]})
    with pytest.raises(FetchError):
        await fetch_page(
            "https://site.test/", resolver=resolver, transport=httpx.MockTransport(big)
        )

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(FetchError):
        await fetch_page(
            "https://site.test/", resolver=resolver, transport=httpx.MockTransport(missing)
        )


def test_html_to_text() -> None:
    assert html_to_text("<style>a{}</style><b>Дом&nbsp;культуры</b>\n\n<i>1</i>") == (
        "Дом культуры 1"
    )


# --- Подпись контакта (§5.3 B.2) -------------------------------------------------------


def test_contact_hash_hex_and_base64() -> None:
    vcf = "BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD"
    digest = hmac.new(b"tok", vcf.encode(), hashlib.sha256).digest()
    assert contact_hash_valid(vcf, digest.hex(), "tok")
    assert contact_hash_valid(vcf, digest.hex().upper(), "tok")
    assert contact_hash_valid(vcf, base64.b64encode(digest).decode(), "tok")
    assert not contact_hash_valid(vcf, digest.hex(), "other")
    assert not contact_hash_valid(vcf + "x", digest.hex(), "tok")
    assert not contact_hash_valid(vcf, "", "tok")


def test_name_similarity_ignores_legal_form() -> None:
    from app.integrations.dadata.party import PartyInfo

    party = PartyInfo(
        inn="7700000000",
        ogrn=None,
        kind="LEGAL",
        status="ACTIVE",
        name_full='МУНИЦИПАЛЬНОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ КУЛЬТУРЫ "ДОМ КУЛЬТУРЫ СЕЛА ИВАНОВКА"',
        name_short='МБУК "ДОМ КУЛЬТУРЫ СЕЛА ИВАНОВКА"',
        names_plain=(normalize_name("ДОМ КУЛЬТУРЫ СЕЛА ИВАНОВКА"),),
        address=None,
        region=None,
        region_code=None,
        raw={},
    )
    assert name_similarity("Дом культуры села Ивановка", party) >= 0.9
    assert name_similarity("Ресторан Пушкин", party) < 0.7


# --- Картинки (§14) ----------------------------------------------------------------------


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 10, 10)).save(out, format="PNG")
    return out.getvalue()


def test_media_process_resizes_to_webp() -> None:
    result = media_service.process(_png(3200, 1600))
    assert (result.width, result.height) == (1600, 800)
    assert result.data[:4] == b"RIFF" and result.data[8:12] == b"WEBP"


def test_media_strips_exif() -> None:
    out = io.BytesIO()
    image = Image.new("RGB", (40, 20))
    exif = Image.Exif()
    exif[0x0112] = 6  # поворот на 90°
    exif[0x010F] = "SecretCam"
    image.save(out, format="JPEG", exif=exif)
    result = media_service.process(out.getvalue())
    assert (result.width, result.height) == (20, 40)
    assert b"SecretCam" not in result.data


def test_media_rejects_non_image() -> None:
    with pytest.raises(AppError) as exc:
        media_service.process(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert exc.value.status_code == 415
    with pytest.raises(AppError) as exc:
        media_service.process(b"\x89PNG\r\n\x1a\n" + b"broken")
    assert exc.value.status_code == 422
