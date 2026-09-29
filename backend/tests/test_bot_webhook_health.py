"""«Бот молчит»: проверка конфигурации webhook, восстановление подписки, статус в /ready."""

import json

import httpx
import pytest
import respx
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.bot import doctor
from app.bot.subscriptions import STATUS_KEY, check_webhook, config_problems
from app.core.config import Settings
from tests.helpers import BOT_TOKEN, WEBHOOK_SECRET, FakeRedis

BASE = "https://max.test"
URL = "https://afisha.example/bot/webhook"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "env": "test",
        "bot_mode": "webhook",
        "public_base_url": "https://afisha.example",
        "max_bot_token": SecretStr(BOT_TOKEN),
        "max_webhook_secret": SecretStr(WEBHOOK_SECRET),
        "max_api_base": BASE,
        "max_bot_username": "afisha_bot",
        "admin_max_user_ids": "42",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_config_problems_empty_url_and_secret() -> None:
    problems = config_problems(
        _settings(public_base_url="http://localhost:8080", max_webhook_secret=None)
    )
    assert "MAX_WEBHOOK_SECRET не задан" in problems
    assert any("https://" in p for p in problems)
    assert any("localhost" in p for p in problems)
    assert config_problems(_settings()) == []


def test_config_problems_bad_secret_format() -> None:
    problems = config_problems(_settings(max_webhook_secret=SecretStr("bad secret!")))
    assert any("5–256" in p for p in problems)


async def test_misconfigured_is_loud_and_saved() -> None:
    redis = FakeRedis()
    with capture_logs() as logs:
        state = await check_webhook(_settings(public_base_url=""), redis, force=False)  # type: ignore[arg-type]
    assert state == "misconfigured"
    assert any(
        e["event"] == "bot_webhook_not_configured" and e["log_level"] == "error" for e in logs
    )
    assert json.loads(redis.data[STATUS_KEY])["state"] == "misconfigured"


@respx.mock
async def test_cron_restores_lost_subscription() -> None:
    respx.get(f"{BASE}/subscriptions").respond(200, json={"subscriptions": []})
    subscribe = respx.post(f"{BASE}/subscriptions").respond(200, json={"success": True})
    redis = FakeRedis()
    with capture_logs() as logs:
        state = await check_webhook(_settings(), redis, force=False)  # type: ignore[arg-type]
    assert state == "restored"
    assert json.loads(subscribe.calls.last.request.content)["url"] == URL
    assert any(e["event"] == "bot_webhook_restored" for e in logs)
    assert json.loads(redis.data[STATUS_KEY])["state"] == "ok"


@respx.mock
async def test_cron_noop_when_subscribed() -> None:
    respx.get(f"{BASE}/subscriptions").respond(200, json={"subscriptions": [{"url": URL}]})
    subscribe = respx.post(f"{BASE}/subscriptions")
    with capture_logs() as logs:
        state = await check_webhook(_settings(), FakeRedis(), force=False)  # type: ignore[arg-type]
    assert state == "ok"
    assert subscribe.call_count == 0
    assert not any(e["event"] == "bot_webhook_restored" for e in logs)


@respx.mock
async def test_max_api_error_saved_as_error() -> None:
    respx.get(f"{BASE}/subscriptions").respond(401, json={"code": "verify.token"})
    redis = FakeRedis()
    state = await check_webhook(_settings(), redis, force=True)  # type: ignore[arg-type]
    assert state == "error"
    assert json.loads(redis.data[STATUS_KEY])["problems"] == ["MAX API ответил 401 verify.token"]


@respx.mock
async def test_doctor_reports_foreign_url_without_token(capsys) -> None:  # type: ignore[no-untyped-def]
    from app.integrations.max import MaxClient

    respx.get(f"{BASE}/me").respond(
        200, json={"user_id": 1, "first_name": "Афиша", "username": "afisha_bot", "is_bot": True}
    )
    respx.get(f"{BASE}/subscriptions").respond(
        200, json={"subscriptions": [{"url": "https://old.example/bot/webhook", "time": 1}]}
    )
    client = MaxClient(BOT_TOKEN, BASE, backoff_s=0)
    problems = await doctor.diagnose(_settings(), client, FakeRedis())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert BOT_TOKEN not in out and WEBHOOK_SECRET not in out
    assert "@afisha_bot" in out
    assert any("Нет подписки" in p for p in problems)
    assert any("другие URL" in p for p in problems)


async def test_ready_shows_bot_state(client: httpx.AsyncClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import health

    monkeypatch.setattr(health, "get_settings", lambda: _settings(max_webhook_secret=None))
    r = await client.get("/ready")
    body = r.json()
    bot = body["bot"] if r.status_code == 200 else body["error"]["details"]["bot"]
    assert bot["mode"] == "webhook"
    assert bot["state"] == "misconfigured"
    assert "MAX_WEBHOOK_SECRET не задан" in bot["problems"]


# --- Локальный запуск: bot-poller должен подниматься `make up` и отмечаться в Redis ---


def test_make_up_starts_bot_poller() -> None:
    """Причина «бот молчит» локально: `make up` не включал профиль compose `local`."""
    from pathlib import Path

    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
    up_recipe = makefile.split("\nup:", 1)[1].split("\n\n", 1)[0]
    assert "--profile local" in up_recipe


async def test_poller_writes_heartbeat() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.bot import poller

    stop = asyncio.Event()

    class OneShotMax:
        async def get_updates(self, marker: int | None) -> tuple[list[object], int]:
            stop.set()
            return [], 7

    redis = FakeRedis()
    ctx = SimpleNamespace(max=OneShotMax(), redis=redis)
    await poller.poll(ctx, stop)  # type: ignore[arg-type]
    assert poller.HEARTBEAT_KEY in redis.data


async def test_doctor_polling_without_heartbeat(capsys) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(bot_mode="polling", max_bot_token=None)
    problems = await doctor.diagnose(settings, None, FakeRedis())  # type: ignore[arg-type]
    assert any("bot-poller" in p and "make up" in p for p in problems)

    redis = FakeRedis()
    redis.data["bot:poller:heartbeat"] = "1700000000"
    problems = await doctor.diagnose(settings, None, redis)  # type: ignore[arg-type]
    assert not any("bot-poller" in p for p in problems)


@respx.mock
async def test_doctor_network_error_is_not_blamed_on_token() -> None:
    from app.integrations.max import MaxClient

    respx.get(f"{BASE}/me").mock(side_effect=httpx.ConnectError("boom"))
    client = MaxClient(BOT_TOKEN, BASE, backoff_s=0)
    problems = await doctor.diagnose(_settings(bot_mode="polling"), client, None)
    assert any("нет связи" in p and "VPN" in p for p in problems)
    assert not any("проверь MAX_BOT_TOKEN" in p for p in problems)


async def test_doctor_checks_worker() -> None:
    settings = _settings(max_bot_token=None)
    problems = await doctor.diagnose(settings, None, FakeRedis())  # type: ignore[arg-type]
    assert any("Воркер не отмечается" in p for p in problems)

    redis = FakeRedis()
    redis.data[doctor.WORKER_HEALTH_KEY] = "Sep-29 14:43:37 j_complete=3 queued=0"
    problems = await doctor.diagnose(settings, None, redis)  # type: ignore[arg-type]
    assert not any("Воркер" in p for p in problems)

    redis.zsets["arq:queue"] = {str(i) for i in range(doctor.QUEUE_BACKLOG)}
    problems = await doctor.diagnose(settings, None, redis)  # type: ignore[arg-type]
    assert any("воркер не успевает" in p for p in problems)


@respx.mock
async def test_doctor_checks_webhook_from_outside() -> None:
    settings = _settings(max_bot_token=None)
    route = respx.post(URL).respond(401)
    problems = await doctor.diagnose(settings, None, None, check_external=True)
    assert route.called
    # Без секрета: заголовок X-Max-Bot-Api-Secret не отправляется.
    assert "x-max-bot-api-secret" not in route.calls.last.request.headers
    assert not any("снаружи" in p or "Caddy" in p for p in problems)

    respx.post(URL).respond(404)
    problems = await doctor.diagnose(settings, None, None, check_external=True)
    assert any("Caddy" in p for p in problems)

    respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    problems = await doctor.diagnose(settings, None, None, check_external=True)
    assert any("недоступен снаружи" in p for p in problems)


@respx.mock
async def test_doctor_names_tls_problem() -> None:
    from app.integrations.max import MaxClient

    respx.get(f"{BASE}/me").mock(
        side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer")
    )
    client = MaxClient(BOT_TOKEN, BASE, backoff_s=0)
    problems = await doctor.diagnose(_settings(bot_mode="polling"), client, None)
    assert any("Russian Trusted CA" in p for p in problems)


def test_ssl_context_trusts_russian_ca() -> None:
    from app.integrations.max.client import RUSSIAN_TRUSTED_CA, ssl_context

    subjects = [str(c.get("subject")) for c in ssl_context().get_ca_certs()]
    assert any("Russian Trusted Root CA" in s for s in subjects)
    assert RUSSIAN_TRUSTED_CA.read_text().count("BEGIN CERTIFICATE") == 2


def test_describe_error_has_no_secrets() -> None:
    from app.integrations.max.client import MaxApiError, describe_error

    assert describe_error(MaxApiError(401, "verify.token", BOT_TOKEN)) == (
        "MAX API ответил 401 verify.token"
    )
    assert "ConnectError" in describe_error(httpx.ConnectError(BOT_TOKEN))
    assert BOT_TOKEN not in describe_error(httpx.ConnectError(BOT_TOKEN))


def test_arq_job_args_hidden_in_logs() -> None:
    import logging

    from app.core.logging import HideJobArgs

    started = logging.LogRecord(
        "arq.worker",
        logging.INFO,
        "",
        0,
        "%6.2fs → %s(%s)%s",
        (0.1, "abc:send_user_message", "123, 'Привет, Иван'", ""),
        None,
    )
    done = logging.LogRecord(
        "arq.worker",
        logging.INFO,
        "",
        0,
        "%6.2fs ← %s ● %s",
        (0.1, "abc:x", "'+79990000000'"),
        None,
    )
    for record in (started, done):
        assert HideJobArgs().filter(record)
    assert "Иван" not in started.getMessage() and "send_user_message" in started.getMessage()
    assert "7999" not in done.getMessage()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", [42]),
        (" 42 , 43 ", [42, 43]),
        ("42,,43,", [42, 43]),
        (",42 ;43 ,", [42, 43]),
        ("", []),
    ],
)
def test_admin_ids_tolerate_spaces_and_commas(raw: str, expected: list[int]) -> None:
    assert _settings(admin_max_user_ids=raw).admin_max_user_ids == expected
