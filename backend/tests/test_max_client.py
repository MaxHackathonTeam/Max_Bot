import json

import httpx
import pytest
import respx

from app.bot.subscriptions import drop_webhooks, ensure_webhook
from app.integrations.max import MaxApiError, MaxClient
from app.integrations.max import keyboards as kb

BASE = "https://max.test"


@pytest.fixture
async def max_client() -> MaxClient:
    return MaxClient("tkn", BASE, backoff_s=0)


@respx.mock
async def test_send_message_uses_auth_header_and_body(max_client: MaxClient) -> None:
    route = respx.post(f"{BASE}/messages").respond(200, json={"message": {"body": {"mid": "m1"}}})
    keyboard = kb.inline_keyboard([[kb.callback("Ок", "ok")]])
    result = await max_client.send_message(chat_id=10, text="Привет", attachments=[keyboard])

    assert result["message"]["body"]["mid"] == "m1"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "tkn"
    assert request.url.params["chat_id"] == "10"
    assert "user_id" not in request.url.params
    body = json.loads(request.content)
    assert body["text"] == "Привет"
    assert body["attachments"][0] == {
        "type": "inline_keyboard",
        "payload": {"buttons": [[{"type": "callback", "text": "Ок", "payload": "ok"}]]},
    }


async def test_send_message_requires_single_recipient(max_client: MaxClient) -> None:
    with pytest.raises(ValueError):
        await max_client.send_message(text="x")
    with pytest.raises(ValueError):
        await max_client.send_message(user_id=1, chat_id=2, text="x")


@respx.mock
async def test_retries_on_5xx_and_429(max_client: MaxClient) -> None:
    route = respx.post(f"{BASE}/answers").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"success": True}),
        ]
    )
    await max_client.answer_callback("cb1", notification="Готово")
    assert route.call_count == 3
    assert route.calls.last.request.url.params["callback_id"] == "cb1"
    assert json.loads(route.calls.last.request.content) == {"notification": "Готово"}


@respx.mock
async def test_retries_on_transport_error_then_gives_up() -> None:
    client = MaxClient("tkn", BASE, retries=2, backoff_s=0)
    route = respx.get(f"{BASE}/me").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(httpx.ConnectError):
        await client.get_me()
    assert route.call_count == 3


@respx.mock
async def test_client_error_not_retried(max_client: MaxClient) -> None:
    route = respx.post(f"{BASE}/messages").respond(
        400, json={"code": "proto.payload", "message": "bad"}
    )
    with pytest.raises(MaxApiError) as exc:
        await max_client.send_message(user_id=1, text="x")
    assert exc.value.status_code == 400
    assert exc.value.code == "proto.payload"
    assert route.call_count == 1


@respx.mock
async def test_get_updates_marker(max_client: MaxClient) -> None:
    route = respx.get(f"{BASE}/updates").respond(
        200, json={"updates": [{"update_type": "bot_started"}], "marker": 7}
    )
    updates, marker = await max_client.get_updates(5, timeout_s=1)
    assert marker == 7
    assert updates[0]["update_type"] == "bot_started"
    params = route.calls.last.request.url.params
    assert params["marker"] == "5"
    assert params["types"] == "bot_started,message_created,message_callback"


@respx.mock
async def test_ensure_webhook_subscribes_and_keeps(max_client: MaxClient) -> None:
    url = "https://afisha.example/bot/webhook"
    types = ["bot_started", "message_created", "message_callback"]
    respx.get(f"{BASE}/subscriptions").mock(
        side_effect=[
            httpx.Response(200, json={"subscriptions": []}),
            httpx.Response(200, json={"subscriptions": [{"url": url, "update_types": types}]}),
        ]
    )
    subscribe = respx.post(f"{BASE}/subscriptions").respond(200, json={"success": True})

    assert await ensure_webhook(max_client, url, "secret_1", force=False) == "subscribed"
    assert await ensure_webhook(max_client, url, "secret_1", force=False) == "ok"
    assert subscribe.call_count == 1
    assert json.loads(subscribe.calls.last.request.content) == {
        "url": url,
        "secret": "secret_1",
        "update_types": types,
    }


@respx.mock
async def test_ensure_webhook_force_resubscribes_with_new_secret(max_client: MaxClient) -> None:
    """Секрет в MAX мог устареть: GET /subscriptions его не показывает, поэтому пересоздаём."""
    url = "https://afisha.example/bot/webhook"
    respx.get(f"{BASE}/subscriptions").respond(200, json={"subscriptions": [{"url": url}]})
    delete = respx.delete(f"{BASE}/subscriptions").respond(200, json={"success": True})
    subscribe = respx.post(f"{BASE}/subscriptions").respond(200, json={"success": True})

    assert await ensure_webhook(max_client, url, "secret_2", force=True) == "resubscribed"
    assert delete.calls.last.request.url.params["url"] == url
    assert json.loads(subscribe.calls.last.request.content)["secret"] == "secret_2"


@respx.mock
async def test_ensure_webhook_fixes_missing_update_types(max_client: MaxClient) -> None:
    url = "https://afisha.example/bot/webhook"
    respx.get(f"{BASE}/subscriptions").respond(
        200, json={"subscriptions": [{"url": url, "update_types": ["message_created"]}]}
    )
    respx.delete(f"{BASE}/subscriptions").respond(200, json={"success": True})
    subscribe = respx.post(f"{BASE}/subscriptions").respond(200, json={"success": True})
    assert await ensure_webhook(max_client, url, "secret_1", force=False) == "resubscribed"
    assert subscribe.call_count == 1


@respx.mock
async def test_drop_webhooks(max_client: MaxClient) -> None:
    respx.get(f"{BASE}/subscriptions").respond(
        200, json={"subscriptions": [{"url": "https://a/x"}, {"url": "https://b/y"}]}
    )
    delete = respx.delete(f"{BASE}/subscriptions").respond(200, json={"success": True})
    assert await drop_webhooks(max_client) == 2
    assert [c.request.url.params["url"] for c in delete.calls] == ["https://a/x", "https://b/y"]


def test_keyboard_validation() -> None:
    button = kb.open_app("Открыть", "afisha_bot", "ev_12")
    assert button == {
        "type": "open_app",
        "text": "Открыть",
        "web_app": "afisha_bot",
        "payload": "ev_12",
    }
    with pytest.raises(ValueError):
        kb.open_app("Открыть", "afisha_bot", "bad payload!")
    with pytest.raises(ValueError):
        kb.callback("", "x")
    with pytest.raises(ValueError):
        kb.callback("x" * 129, "x")
