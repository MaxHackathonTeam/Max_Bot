"""Скачивание страницы организации с защитой от SSRF (§5.3 B.3, §14).

- только https и порт 443;
- хост резолвится заранее, приватные, loopback, link-local и прочие не-глобальные адреса
  запрещены; соединение идёт на проверенный IP (Host и SNI — исходное имя), поэтому
  подмена DNS между проверкой и запросом не помогает;
- не больше 3 редиректов, каждый проверяется заново;
- общий таймаут 10 с, тело не больше 2 МБ.
"""

import asyncio
import html
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import structlog

log = structlog.get_logger(__name__)

TIMEOUT_S = 10.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "afisha-ryadom-verifier/1.0"

Resolver = Callable[[str], Awaitable[list[str]]]


class UnsafeUrlError(Exception):
    """Адрес запрещён политикой (схема, порт, приватный IP)."""


class FetchError(Exception):
    """Страницу не удалось скачать (сеть, статус, размер, таймаут)."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status: int
    html: str

    @property
    def text(self) -> str:
        return html_to_text(self.html)


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> tuple[str, str]:
    """(host, path?query) для https-URL без логина и нестандартного порта."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise UnsafeUrlError("Нужна ссылка https://")
    if parts.username or parts.password:
        raise UnsafeUrlError("Ссылка с логином не подходит")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("В ссылке нет адреса сайта")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("Некорректный порт") from exc
    if port not in (None, 443):
        raise UnsafeUrlError("Разрешён только стандартный порт https")
    target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    return host, target


async def _resolve_public(host: str, resolver: Resolver) -> str:
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = await resolver(host)
        except OSError as exc:
            raise FetchError("Сайт не найден") from exc
    if not addresses:
        raise FetchError("Сайт не найден")
    # Все адреса должны быть публичными: иначе round-robin DNS обходит проверку.
    if not all(is_public_ip(a) for a in addresses):
        raise UnsafeUrlError("Адрес сайта ведёт во внутреннюю сеть")
    return addresses[0]


async def _get_once(
    http: httpx.AsyncClient, host: str, target: str, ip: str
) -> tuple[int, httpx.Headers, bytes]:
    ip_host = f"[{ip}]" if ":" in ip else ip
    async with http.stream(
        "GET",
        f"https://{ip_host}{target}",
        headers={"Host": host, "User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
        extensions={"sni_hostname": host},
    ) as response:
        if response.is_redirect:
            return response.status_code, response.headers, b""
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise FetchError("Страница больше 2 МБ")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise FetchError("Страница больше 2 МБ")
        return response.status_code, response.headers, bytes(body)


def _decode(body: bytes, headers: httpx.Headers) -> str:
    match = re.search(r"charset=([\w-]+)", headers.get("content-type", ""), re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def fetch_page(
    url: str,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: float = TIMEOUT_S,
) -> FetchedPage:
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout_s, transport=transport
    ) as http:
        try:
            async with asyncio.timeout(timeout_s):
                for _ in range(MAX_REDIRECTS + 1):
                    host, target = check_url(current)
                    ip = await _resolve_public(host, resolver)
                    status, headers, body = await _get_once(http, host, target, ip)
                    if 300 <= status < 400:
                        location = headers.get("location")
                        if not location:
                            raise FetchError("Сайт вернул редирект без адреса")
                        current = urljoin(current, location)
                        continue
                    if status >= 400:
                        raise FetchError(f"Сайт ответил ошибкой {status}")
                    log.info("safe_fetch_ok", host=host, status=status, size=len(body))
                    return FetchedPage(url=current, status=status, html=_decode(body, headers))
        except TimeoutError as exc:
            raise FetchError("Сайт не ответил за 10 секунд") from exc
        except httpx.HTTPError as exc:
            log.info("safe_fetch_failed", error=type(exc).__name__)
            raise FetchError("Не удалось открыть сайт") from exc
    raise FetchError("Слишком много перенаправлений")


_DROP_BLOCKS = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def html_to_text(raw: str) -> str:
    text = _DROP_BLOCKS.sub(" ", raw)
    text = _TAGS.sub(" ", text)
    return _SPACES.sub(" ", html.unescape(text)).strip()
