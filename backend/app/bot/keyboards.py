"""Клавиатуры бота (§12)."""

from typing import Any

from app.bot import texts
from app.integrations.max import keyboards as kb

CB_CONSENT_ACCEPT = "consent:accept"
CB_MENU = "menu:open"
CB_TODAY = "menu:today"
CB_WEEKEND = "menu:weekend"
CB_PUSHKIN = "menu:pushkin"
CB_SAVED = "menu:saved"
CB_SETTINGS = "menu:settings"
CB_ORG = "menu:org"

# Пункты меню, которые появятся на следующих этапах: пока отвечаем тостом «скоро».
SOON_CALLBACKS = frozenset({CB_TODAY, CB_WEEKEND, CB_PUSHKIN, CB_SAVED, CB_SETTINGS, CB_ORG})


def main_menu(web_app: str | None) -> dict[str, Any]:
    rows: list[list[kb.Button]] = []
    if web_app:
        rows.append([kb.open_app(texts.MENU_OPEN_APP, web_app)])
    rows += [
        [
            kb.callback(texts.MENU_TODAY, CB_TODAY),
            kb.callback(texts.MENU_WEEKEND, CB_WEEKEND),
            kb.callback(texts.MENU_PUSHKIN, CB_PUSHKIN),
        ],
        [kb.callback(texts.MENU_SAVED, CB_SAVED), kb.callback(texts.MENU_SETTINGS, CB_SETTINGS)],
        [kb.callback(texts.MENU_ORG, CB_ORG)],
    ]
    return kb.inline_keyboard(rows)


def consent() -> dict[str, Any]:
    return kb.inline_keyboard([[kb.callback(texts.CONSENT_ACCEPT_BUTTON, CB_CONSENT_ACCEPT)]])


def menu_button() -> dict[str, Any]:
    return kb.inline_keyboard([[kb.callback(texts.MENU_BUTTON, CB_MENU)]])


def open_app_with(web_app: str, payload: str) -> dict[str, Any]:
    return kb.inline_keyboard([[kb.open_app(texts.DEEPLINK_OPEN_BUTTON, web_app, payload)]])
