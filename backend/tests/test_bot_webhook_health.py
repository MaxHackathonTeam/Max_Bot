"""«Бот молчит»: проверка конфигурации webhook, восстановление подписки, статус в /ready."""

import json

import httpx
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
    assert json.loads(redis.data[STATUS_KEY])["problems"] == ["MAX API: MaxApiError"]


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
