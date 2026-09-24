"""Конструкторы inline-клавиатур MAX (schema.yaml: InlineKeyboardAttachmentRequest, Button)."""

import re
from typing import Any

Button = dict[str, Any]

# Ограничения схемы: текст кнопки 1–128, payload callback ≤ 1024, open_app ≤ 512 и [\w-].
_OPEN_APP_PAYLOAD = re.compile(r"^[\w-]{0,512}$")


def _text(text: str) -> str:
    if not 1 <= len(text) <= 128:
        raise ValueError("Текст кнопки должен быть от 1 до 128 символов")
    return text


def callback(text: str, payload: str) -> Button:
    if len(payload) > 1024:
        raise ValueError("payload callback-кнопки длиннее 1024")
    return {"type": "callback", "text": _text(text), "payload": payload}


def link(text: str, url: str) -> Button:
    return {"type": "link", "text": _text(text), "url": url[:2048]}


def open_app(text: str, web_app: str, payload: str | None = None) -> Button:
    """Кнопка запуска мини-приложения. web_app — публичное имя бота."""
    button: Button = {"type": "open_app", "text": _text(text), "web_app": web_app}
    if payload:
        if not _OPEN_APP_PAYLOAD.match(payload):
            raise ValueError("payload open_app: только [A-Za-z0-9_-], до 512 символов")
        button["payload"] = payload
    return button


def request_geo_location(text: str, *, quick: bool = False) -> Button:
    return {"type": "request_geo_location", "text": _text(text), "quick": quick}


def inline_keyboard(rows: list[list[Button]]) -> dict[str, Any]:
    return {"type": "inline_keyboard", "payload": {"buttons": [r for r in rows if r]}}
