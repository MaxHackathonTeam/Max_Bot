"""Общий вызов внешних HTTP API: таймаут, ретраи на 429/5xx, логи без параметров (ПДн)."""

import asyncio
import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ExternalApiError(Exception):
    def __init__(self, service: str, status_code: int | None, message: str) -> None:
        super().__init__(f"{service} {status_code}: {message}")
        self.service = service
        self.status_code = status_code


async def request_json(
    http: httpx.AsyncClient,
    service: str,
    method: str,
    url: str,
    *,
    retries: int = 2,
    backoff_s: float = 0.5,
    **kwargs: Any,
) -> Any:
    attempt = 0
    while True:
        started = time.perf_counter()
        try:
            response = await http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt >= retries:
                log.warning("external_api_error", service=service, error=type(exc).__name__)
                raise ExternalApiError(service, None, type(exc).__name__) from exc
            await asyncio.sleep(backoff_s * 2**attempt)
            attempt += 1
            continue
        log.info(
            "external_api_call",
            service=service,
            method=method,
            path=response.request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            attempt=attempt,
        )
        if response.status_code in RETRY_STATUSES and attempt < retries:
            await asyncio.sleep(backoff_s * 2**attempt)
            attempt += 1
            continue
        if response.is_error:
            raise ExternalApiError(service, response.status_code, response.reason_phrase)
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalApiError(service, response.status_code, "invalid json") from exc
