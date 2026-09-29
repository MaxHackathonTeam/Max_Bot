"""Клавиатуры бота (§12).

Payload callback-кнопок — «префикс:аргументы», до 1024 символов (schema.yaml: CallbackButton).
"""

from collections.abc import Mapping, Sequence
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
CB_FIND = "menu:find"
CB_ADD = "menu:add"
CB_CITY = "menu:city"
CB_MY = "menu:my"
CB_KIDS = "menu:kids"
CB_FREE = "menu:free"

# Пункты меню, которые появятся на следующих этапах: пока отвечаем тостом «скоро».
SOON_CALLBACKS: frozenset[str] = frozenset()

# Подборки: пункт меню → пресет.
FEED_BY_MENU = {
    CB_TODAY: "today",
    CB_WEEKEND: "weekend",
    CB_PUSHKIN: "pushkin",
    CB_KIDS: "kids",
    CB_FREE: "free",
}
# Лента в payload: o — «Официальные», c — «От сообщества».
TIER_CODES = {"o": "official", "c": "community"}

# Префиксы callback с аргументами.
P_LOCALITY = "loc"  # loc:<locality_id>
P_INTEREST = "int"  # int:<slug> | int:done
P_FEED = "feed"  # feed:<preset>:<radius>:<o|c>:<offset>[:<cursor>]
P_SAVE = "save"  # save:<event_id>:<session_id>
P_UNSAVE = "unsave"  # unsave:<event_id>:<session_id>
P_RADIUS = "rad"  # rad:<km>
P_ADMIN = (
    "adm"  # adm:e:<event_id>:<approve|reject|hide> | adm:v:<id>:<approve|reject> | adm:r:<org>
)
P_WEB_LOGIN = "weblogin"  # weblogin:<code> | weblogin:no:<code>
P_ADD = "add"  # мастер «Добавить афишу», см. app.bot.add_event

INTERESTS_DONE = "done"
CB_SET_LOCALITY = "set:loc"
CB_SET_INTERESTS = "set:int"
CB_SET_REMINDERS = "set:rem"
CB_SET_DIGEST = "set:dig"
CB_DELETE_ASK = "del:ask"
CB_DELETE_YES = "del:yes"
CB_DELETE_NO = "del:no"


def main_menu(web_app: str | None, place: str | None) -> dict[str, Any]:
    city = texts.MENU_CITY.format(name=place[:100]) if place else texts.MENU_CITY_NONE
    rows: list[list[kb.Button]] = [
        [kb.callback(texts.MENU_FIND, CB_FIND), kb.callback(texts.MENU_ADD, CB_ADD)],
        [kb.callback(city, CB_CITY)],
        [kb.callback(texts.MENU_MY, CB_MY), kb.callback(texts.MENU_ORG, CB_ORG)],
        [kb.callback(texts.MENU_SAVED, CB_SAVED), kb.callback(texts.MENU_SETTINGS, CB_SETTINGS)],
    ]
    if web_app:
        rows.append([kb.open_app(texts.MENU_OPEN_APP, web_app)])
    return kb.inline_keyboard(rows)


def find_menu() -> dict[str, Any]:
    return kb.inline_keyboard(
        [
            [kb.callback(texts.MENU_TODAY, CB_TODAY), kb.callback(texts.MENU_WEEKEND, CB_WEEKEND)],
            [kb.callback(texts.MENU_KIDS, CB_KIDS), kb.callback(texts.MENU_FREE, CB_FREE)],
            [kb.callback(texts.MENU_PUSHKIN, CB_PUSHKIN)],
            [kb.callback(texts.MENU_BUTTON, CB_MENU)],
        ]
    )


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


def feed_payload(
    preset: str, radius: int, tier: str = "o", offset: int = 0, cursor: str | None = None
) -> str:
    return f"{P_FEED}:{preset}:{radius}:{tier}:{offset}" + (f":{cursor}" if cursor else "")


def _details(web_app: str | None, n: int, event_id: int, url: str | None) -> kb.Button | None:
    """«Подробнее на сайте»: ссылка, если сайт на https, иначе карточка в мини-приложении."""
    label = texts.FEED_DETAILS_BUTTON.format(n=n)
    if url:
        return kb.link(label, url)
    if web_app:
        return kb.open_app(label, web_app, f"ev_{event_id}")
    return None


FeedItem = tuple[int, int | None, str | None]  # event_id, session_id, ссылка на сайт


def _feed_rows(
    web_app: str | None,
    items: Sequence[FeedItem],
    offset: int,
    orgs: Mapping[int, int] | None = None,
) -> list[list[kb.Button]]:
    rows: list[list[kb.Button]] = []
    for n, (event_id, session_id, url) in enumerate(items, start=offset + 1):
        row: list[kb.Button] = []
        details = _details(web_app, n, event_id, url)
        if details is not None:
            row.append(details)
        if session_id is not None:
            row.append(kb.callback(texts.FEED_SAVE_BUTTON, f"{P_SAVE}:{event_id}:{session_id}"))
        if orgs and event_id in orgs:
            row.append(kb.callback(texts.ORG_ABOUT_BUTTON, org_profile_payload(orgs[event_id])))
        if row:
            rows.append(row)
    return rows


def feed(
    web_app: str | None,
    items: Sequence[FeedItem],
    *,
    preset: str | None,
    radius: int,
    tier: str = "o",
    next_cursor: str | None = None,
    offset: int = 0,
    orgs: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Строка на событие: [№ Подробнее на сайте] [⭐ Пойду] [🏛 Организатор]; внизу «Ещё» и «Меню».

    orgs — event_id → organization_id для кнопки «Об организаторе».
    """
    rows = _feed_rows(web_app, items, offset, orgs)
    bottom: list[kb.Button] = []
    if next_cursor and preset:
        more = feed_payload(preset, radius, tier, offset + len(items), next_cursor)
        # Курсор длинный: payload callback — до 1024 символов (schema.yaml).
        if len(more) <= 1024:
            bottom.append(kb.callback(texts.FEED_MORE_BUTTON, more))
    if web_app:
        bottom.append(kb.open_app(texts.FEED_ALL_BUTTON, web_app, f"feed_{preset or 'today'}"))
    if bottom:
        rows.append(bottom)
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def empty_here(*, preset: str | None, wider: int | None) -> dict[str, Any]:
    rows: list[list[kb.Button]] = [[kb.callback(texts.ADD_FIRST_BUTTON, CB_ADD)]]
    if wider is not None and preset:
        label = texts.FEED_WIDEN_BUTTON.format(radius=wider)
        rows.append([kb.callback(label, feed_payload(preset, wider))])
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


def org_menu(web_app: str | None) -> dict[str, Any]:
    rows: list[list[kb.Button]] = []
    if web_app:
        rows.append([kb.open_app(texts.ORG_OPEN_BUTTON, web_app, "org_0")])
        rows.append([kb.open_app(texts.ORG_NEW_EVENT_BUTTON, web_app, "draft_0")])
    rows.append([kb.callback(texts.ORG_SEARCH_BUTTON, CB_ORG_FIND)])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def phone_request() -> dict[str, Any]:
    return kb.inline_keyboard([[kb.request_contact(texts.PHONE_REQUEST_BUTTON)]])


def queue_event(web_app: str | None, event_id: int, org_id: int | None) -> dict[str, Any]:
    rows = [
        [
            kb.callback(texts.QUEUE_APPROVE_BUTTON, f"{P_ADMIN}:e:{event_id}:approve"),
            kb.callback(texts.QUEUE_REJECT_BUTTON, f"{P_ADMIN}:e:{event_id}:reject"),
        ],
        [kb.callback(texts.QUEUE_HIDE_BUTTON, f"{P_ADMIN}:e:{event_id}:hide")],
    ]
    if org_id is not None:
        rows.append([kb.callback(texts.QUEUE_REVOKE_BUTTON, f"{P_ADMIN}:r:{org_id}")])
    if web_app:
        rows.append([kb.open_app(texts.QUEUE_OPEN_BUTTON, web_app, f"ev_{event_id}")])
    return kb.inline_keyboard(rows)


def queue_verification(request_id: int) -> dict[str, Any]:
    return kb.inline_keyboard(
        [
            [
                kb.callback(texts.QUEUE_APPROVE_BUTTON, f"{P_ADMIN}:v:{request_id}:approve"),
                kb.callback(texts.QUEUE_REJECT_BUTTON, f"{P_ADMIN}:v:{request_id}:reject"),
            ]
        ]
    )


def open_link(web_app: str, payload: str) -> dict[str, Any]:
    return kb.inline_keyboard([[kb.open_app(texts.EVENT_OPEN_BUTTON, web_app, payload)]])


def web_login_confirm(code: str) -> dict[str, Any]:
    return kb.inline_keyboard(
        [
            [
                kb.callback(texts.WEB_LOGIN_BUTTON, f"{P_WEB_LOGIN}:{code}"),
                kb.callback(texts.WEB_LOGIN_DENY_BUTTON, f"{P_WEB_LOGIN}:no:{code}"),
            ]
        ]
    )


def my_events(web_app: str | None, items: Sequence[tuple[int, str | None]]) -> dict[str, Any]:
    """items — (event_id, ссылка на сайт)."""
    rows: list[list[kb.Button]] = []
    buttons: list[kb.Button] = []
    for n, (event_id, url) in enumerate(items, start=1):
        label = texts.MY_OPEN_BUTTON.format(n=n)
        if url:
            buttons.append(kb.link(label, url))
        elif web_app:
            buttons.append(kb.open_app(label, web_app, f"ev_{event_id}"))
    rows += [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([kb.callback(texts.MENU_ADD, CB_ADD), kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def link_and_menu(label: str, url: str | None, web_app: str | None, payload: str) -> dict[str, Any]:
    rows: list[list[kb.Button]] = []
    if url:
        rows.append([kb.link(label, url)])
    elif web_app:
        rows.append([kb.open_app(label, web_app, payload)])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


# --- Мастер «Добавить афишу» ----------------------------------------------------------------
# add:steps | add:back | add:cancel | add:skip | add:send | add:org:<id|0> | add:loc:<id>
# add:venue:<id|new> | add:cat:<slug> | add:price:<free|donation> | add:edit:<шаг>

CB_ADD_STEPS = f"{P_ADD}:steps"
CB_ADD_BACK = f"{P_ADD}:back"
CB_ADD_CANCEL = f"{P_ADD}:cancel"
CB_ADD_SKIP = f"{P_ADD}:skip"
CB_ADD_SEND = f"{P_ADD}:send"


def _add_nav(*, back: bool = True, skip: bool = False) -> list[list[kb.Button]]:
    rows: list[list[kb.Button]] = []
    if skip:
        rows.append([kb.callback(texts.ADD_SKIP, CB_ADD_SKIP)])
    nav = [kb.callback(texts.ADD_BACK, CB_ADD_BACK)] if back else []
    nav.append(kb.callback(texts.ADD_CANCEL, CB_ADD_CANCEL))
    rows.append(nav)
    return rows


def add_start() -> dict[str, Any]:
    rows = [[kb.callback(texts.ADD_STEPS_BUTTON, CB_ADD_STEPS)], *_add_nav(back=False)]
    return kb.inline_keyboard(rows)


def add_step(*, back: bool = True, skip: bool = False) -> dict[str, Any]:
    return kb.inline_keyboard(_add_nav(back=back, skip=skip))


def add_orgs(orgs: Sequence[tuple[int, str]]) -> dict[str, Any]:
    rows = [[kb.callback(f"🏛 {name}"[:128], f"{P_ADD}:org:{org_id}")] for org_id, name in orgs]
    rows.append([kb.callback(texts.ADD_ORG_SELF, f"{P_ADD}:org:0")])
    rows += _add_nav(back=False)
    return kb.inline_keyboard(rows)


def add_places(options: Sequence[tuple[int, str]]) -> dict[str, Any]:
    rows = [[kb.callback(label[:128], f"{P_ADD}:loc:{loc_id}")] for loc_id, label in options]
    return kb.inline_keyboard(rows + _add_nav())


def add_venues(options: Sequence[tuple[int, str]], new_name: str | None) -> dict[str, Any]:
    rows = [[kb.callback(label[:128], f"{P_ADD}:venue:{v_id}")] for v_id, label in options]
    if new_name:
        label = texts.ADD_VENUE_NEW.format(name=new_name)[:128]
        rows.append([kb.callback(label, f"{P_ADD}:venue:new")])
    return kb.inline_keyboard(rows + _add_nav(skip=True))


def add_categories() -> dict[str, Any]:
    buttons = [kb.callback(f"{c.emoji} {c.name}", f"{P_ADD}:cat:{c.slug}") for c in CATEGORIES]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return kb.inline_keyboard(rows + _add_nav())


def add_price() -> dict[str, Any]:
    rows = [
        [
            kb.callback(texts.ADD_PRICE_FREE, f"{P_ADD}:price:free"),
            kb.callback(texts.ADD_PRICE_DONATION, f"{P_ADD}:price:donation"),
        ]
    ]
    return kb.inline_keyboard(rows + _add_nav())


def add_preview(steps: Sequence[str]) -> dict[str, Any]:
    edits = [
        kb.callback(texts.ADD_EDIT.format(name=texts.ADD_FIELD_NAMES[step]), f"{P_ADD}:edit:{step}")
        for step in steps
    ]
    rows = [[kb.callback(texts.ADD_SUBMIT, CB_ADD_SEND)]]
    rows += [edits[i : i + 2] for i in range(0, len(edits), 2)]
    return kb.inline_keyboard(rows + _add_nav())


# --- Модерация: уведомления админам ---------------------------------------------------------

P_MOD = "mod"  # mod:<e|v>:<id>:<approve|reject> — кнопки в уведомлении модератору


def moderation_alert(kind: str, entity_id: int, url: str | None) -> dict[str, Any]:
    rows: list[list[kb.Button]] = [
        [
            kb.callback(texts.MOD_APPROVE, f"{P_MOD}:{kind}:{entity_id}:approve"),
            kb.callback(texts.MOD_REJECT, f"{P_MOD}:{kind}:{entity_id}:reject"),
        ]
    ]
    if url:
        rows.append([kb.link(texts.MOD_OPEN_SITE, url)])
    return kb.inline_keyboard(rows)


def moderation_closed(url: str | None) -> dict[str, Any] | None:
    """После решения кнопки убираем, ссылку на карточку оставляем."""
    return kb.inline_keyboard([[kb.link(texts.MOD_OPEN_SITE, url)]]) if url else None


# --- Профиль организации ------------------------------------------------------------------
# orgp:<id> — профиль | orgp:ev:<id>:<o|c>:<offset>[:<cursor>] — афиши | orgp:find — поиск

P_ORG_PUBLIC = "orgp"
CB_ORG_FIND = f"{P_ORG_PUBLIC}:find"
ORG_BUTTON_MAX = 64


def org_profile_payload(org_id: int) -> str:
    return f"{P_ORG_PUBLIC}:{org_id}"


def org_events_payload(
    org_id: int, tier: str = "o", offset: int = 0, cursor: str | None = None
) -> str:
    return f"{P_ORG_PUBLIC}:ev:{org_id}:{tier}:{offset}" + (f":{cursor}" if cursor else "")


def _org_site(label: str, org_id: int, url: str | None, web_app: str | None) -> kb.Button | None:
    if url:
        return kb.link(label, url)
    if web_app:
        return kb.open_app(label, web_app, f"org_{org_id}")
    return None


def org_profile(
    org_id: int, *, url: str | None, web_app: str | None, official: int, community: int
) -> dict[str, Any]:
    """[Афиши организации] (лента с событиями), [От сообщества], [Открыть на сайте], [Меню]."""
    rows: list[list[kb.Button]] = []
    if official or not community:
        label = texts.ORG_EVENTS_BUTTON.format(count=official)
        rows.append([kb.callback(label, org_events_payload(org_id, "o"))])
    if community:
        label = texts.ORG_COMMUNITY_BUTTON.format(count=community)
        rows.append([kb.callback(label, org_events_payload(org_id, "c"))])
    site = _org_site(texts.ORG_SITE_BUTTON, org_id, url, web_app)
    if site is not None:
        rows.append([site])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def org_events(
    web_app: str | None,
    items: Sequence[FeedItem],
    *,
    org_id: int,
    tier: str,
    next_cursor: str | None,
    offset: int,
    other: tuple[str, int] | None = None,
) -> dict[str, Any]:
    """Афиши одной ленты; other — (код другой ленты, сколько там событий)."""
    rows = _feed_rows(web_app, items, offset)
    if next_cursor:
        more = org_events_payload(org_id, tier, offset + len(items), next_cursor)
        if len(more) <= 1024:
            rows.append([kb.callback(texts.FEED_MORE_BUTTON, more)])
    if other is not None and other[1]:
        template = texts.ORG_COMMUNITY_BUTTON if other[0] == "c" else texts.ORG_OFFICIAL_BUTTON
        label = template.format(count=other[1])
        rows.append([kb.callback(label, org_events_payload(org_id, other[0]))])
    rows.append([kb.callback(texts.ORG_BACK_BUTTON, org_profile_payload(org_id))])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)


def org_search_results(options: Sequence[tuple[int, str]]) -> dict[str, Any]:
    rows = [
        [kb.callback(label[:ORG_BUTTON_MAX], org_profile_payload(org_id))]
        for org_id, label in options
    ]
    rows.append([kb.callback(texts.ORG_SEARCH_AGAIN_BUTTON, CB_ORG_FIND)])
    rows.append([kb.callback(texts.MENU_BUTTON, CB_MENU)])
    return kb.inline_keyboard(rows)
