"""Клавиатуры бота (§12).

Payload callback-кнопок — «префикс:аргументы», до 1024 символов (schema.yaml: CallbackButton).
"""

from collections.abc import Sequence
from typing import Any

from app.bot import texts
from app.integrations.max import keyboards as kb
from app.services.categories import CATEGORIES

CB_CONSENT_ACCEPT = "consent:accept"
CB_MENU = "menu:open"
CB_TODAY = "menu:today"
CB_WEEKEND = "menu:weekend"
CB_PUSHKIN = "menu:pushkin"
CB_SAVED = "menu:saved"
CB_SETTINGS = "menu:settings"
CB_ORG = "menu:org"

# Пункты меню, которые появятся на следующих этапах: пока отвечаем тостом «скоро».
SOON_CALLBACKS = frozenset({CB_ORG})

# Подборки: пункт меню → пресет.
FEED_BY_MENU = {CB_TODAY: "today", CB_WEEKEND: "weekend", CB_PUSHKIN: "pushkin"}

# Префиксы callback с аргументами.
P_LOCALITY = "loc"  # loc:<locality_id>
P_INTEREST = "int"  # int:<slug> | int:done
P_FEED = "feed"  # feed:<preset>:<radius>:<offset>[:<cursor>]
P_SAVE = "save"  # save:<event_id>:<session_id>
P_UNSAVE = "unsave"  # unsave:<event_id>:<session_id>
P_RADIUS = "rad"  # rad:<km>

INTERESTS_DONE = "done"
CB_SET_LOCALITY = "set:loc"
CB_SET_INTERESTS = "set:int"
CB_SET_REMINDERS = "set:rem"
CB_SET_DIGEST = "set:dig"
CB_DELETE_ASK = "del:ask"
CB_DELETE_YES = "del:yes"
CB_DELETE_NO = "del:no"


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


def ask_locality() -> dict[str, Any]:
    return kb.inline_keyboard([[kb.request_geo_location(texts.SEND_GEO_BUTTON)]])


def localities(options: Sequence[tuple[int, str]]) -> dict[str, Any]:
    """options — (id, подпись); по одной кнопке в строке."""
    rows = [[kb.callback(label[:128], f"{P_LOCALITY}:{loc_id}")] for loc_id, label in options]
    rows.append([kb.request_geo_location(texts.SEND_GEO_BUTTON)])
    return kb.inline_keyboard(rows)


def interests(selected: Sequence[str]) -> dict[str, Any]:
    buttons = [
        kb.callback(
            texts.INTEREST_ON.format(name=c.name)
            if c.slug in selected
            else texts.INTEREST_OFF.format(emoji=c.emoji, name=c.name),
            f"{P_INTEREST}:{c.slug}",
        )
        for c in CATEGORIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([kb.callback(texts.INTERESTS_DONE_BUTTON, f"{P_INTEREST}:{INTERESTS_DONE}")])
    return kb.inline_keyboard(rows)


def feed_payload(preset: str, radius: int, offset: int = 0, cursor: str | None = None) -> str:
    return f"{P_FEED}:{preset}:{radius}:{offset}" + (f":{cursor}" if cursor else "")


def feed(
    web_app: str | None,
    items: Sequence[tuple[int, int | None]],
    *,
    preset: str,
    radius: int,
    next_cursor: str | None,
    offset: int = 0,
) -> dict[str, Any]:
    """items — (event_id, session_id); строка на событие: [№ Подробнее] [⭐ Пойду]."""
    rows: list[list[kb.Button]] = []
    for n, (event_id, session_id) in enumerate(items, start=offset + 1):
        row: list[kb.Button] = []
        if web_app:
            label = texts.FEED_DETAILS_BUTTON.format(n=n)
            row.append(kb.open_app(label, web_app, f"ev_{event_id}"))
        if session_id is not None:
            row.append(kb.callback(texts.FEED_SAVE_BUTTON, f"{P_SAVE}:{event_id}:{session_id}"))
        rows.append(row)
    bottom: list[kb.Button] = []
    if next_cursor:
        more = feed_payload(preset, radius, offset + len(items), next_cursor)
        bottom.append(kb.callback(texts.FEED_MORE_BUTTON, more))
    if web_app:
        bottom.append(kb.open_app(texts.FEED_ALL_BUTTON, web_app, f"feed_{preset}"))
    rows.append(bottom)
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def feed_empty(web_app: str | None, *, preset: str, wider: int | None) -> dict[str, Any]:
    rows: list[list[kb.Button]] = []
    if wider is not None:
        label = texts.FEED_WIDEN_BUTTON.format(radius=wider)
        rows.append([kb.callback(label, feed_payload(preset, wider))])
    if web_app:
        rows.append([kb.open_app(texts.FEED_ALL_BUTTON, web_app, f"feed_{preset}")])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def saved(web_app: str | None, items: Sequence[tuple[int, int]]) -> dict[str, Any]:
    """items — (event_id, session_id)."""
    rows: list[list[kb.Button]] = []
    for n, (event_id, session_id) in enumerate(items, start=1):
        row: list[kb.Button] = []
        if web_app:
            row.append(
                kb.open_app(texts.FEED_DETAILS_BUTTON.format(n=n), web_app, f"ev_{event_id}")
            )
        label = texts.SAVED_UNSAVE_BUTTON.format(n=n)
        row.append(kb.callback(label, f"{P_UNSAVE}:{event_id}:{session_id}"))
        rows.append(row)
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def settings(radius: int, *, reminders: bool, digest: bool) -> dict[str, Any]:
    def state(on: bool) -> str:
        return texts.SETTINGS_ON if on else texts.SETTINGS_OFF

    radius_row = [
        kb.callback(
            (
                texts.SETTINGS_RADIUS_CURRENT if km == radius else texts.SETTINGS_RADIUS_BUTTON
            ).format(radius=km),
            f"{P_RADIUS}:{km}",
        )
        for km in (5, 15, 30, 50)
    ]
    return kb.inline_keyboard(
        [
            [
                kb.callback(texts.SETTINGS_PLACE_BUTTON, CB_SET_LOCALITY),
                kb.callback(texts.SETTINGS_INTERESTS_BUTTON, CB_SET_INTERESTS),
            ],
            radius_row,
            [
                kb.callback(
                    texts.SETTINGS_REMINDERS_BUTTON.format(state=state(reminders)),
                    CB_SET_REMINDERS,
                ),
                kb.callback(
                    texts.SETTINGS_DIGEST_BUTTON.format(state=state(digest)), CB_SET_DIGEST
                ),
            ],
            [kb.callback(texts.SETTINGS_DELETE_BUTTON, CB_DELETE_ASK)],
            [kb.callback(texts.MENU_BUTTON, CB_MENU)],
        ]
    )


def delete_confirm() -> dict[str, Any]:
    return kb.inline_keyboard(
        [
            [
                kb.callback(texts.DELETE_YES_BUTTON, CB_DELETE_YES),
                kb.callback(texts.DELETE_NO_BUTTON, CB_DELETE_NO),
            ]
        ]
    )
