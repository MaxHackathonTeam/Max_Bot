"""Все тексты бота (§12): дружелюбно, на «ты», эмодзи умеренно."""

GREETING = (
    "Привет, {name}! 👋\n"
    "Я «Афиша рядом» — подскажу, куда сходить в твоём городе или селе: "
    "концерты, кино, мастер-классы, праздники и всё, что по Пушкинской карте."
)
GREETING_NO_NAME = GREETING.replace(", {name}", "")

CONSENT = (
    "Чтобы сохранять события, присылать напоминания и публиковать анонсы, "
    "мне нужно твоё согласие с документами:\n"
    "• Условия использования: {terms_url}\n"
    "• Политика обработки персональных данных: {privacy_url}\n\n"
    "Смотреть афишу можно и без согласия."
)
CONSENT_ACCEPT_BUTTON = "✅ Принимаю"
CONSENT_ACCEPTED_TOAST = "Спасибо! Согласие сохранено"

MENU = "Что посмотрим?"
MENU_OPEN_APP = "📍 Открыть афишу"
MENU_TODAY = "Сегодня"
MENU_WEEKEND = "Выходные"
MENU_PUSHKIN = "💳 По Пушкинской"
MENU_SAVED = "Мои «Пойду»"
MENU_SETTINGS = "Настройки"
MENU_ORG = "Я организатор"
MENU_BUTTON = "Меню"

SOON_TOAST = "Скоро будет! Пока загляни в афишу 📍"

HELP = (
    "Вот что я умею:\n"
    "/menu — главное меню\n"
    "/today — что сегодня\n"
    "/weekend — что на выходных\n"
    "/saved — мои «Пойду»\n"
    "/settings — место, радиус, интересы\n"
    "/delete_me — удалить мои данные\n"
    "/help — эта подсказка\n\n"
    "Все события, фильтры и карточки — в приложении: жми «📍 Открыть афишу»."
)

UNKNOWN_TEXT = "Пока я понимаю только команды. Открой меню или афишу 👇"

# --- Онбординг: населённый пункт и интересы (FR-ONB-2, FR-ONB-3) ---

ASK_LOCALITY = (
    "Где ты живёшь? Отправь геопозицию кнопкой ниже или напиши название "
    "города или села — например, «Савино»."
)
SEND_GEO_BUTTON = "📍 Отправить геопозицию"
LOCALITY_CHOOSE = "Выбери свой населённый пункт:"
LOCALITY_NOT_FOUND = "Не нашёл «{query}» 🤔 Попробуй написать иначе или отправь геопозицию."
LOCALITY_TOO_SHORT = "Напиши хотя бы пару букв названия."
LOCALITY_GEO_NOT_FOUND = (
    "Рядом с тобой не нашёл населённых пунктов в справочнике. Напиши название текстом."
)
LOCALITY_SAVED = "Запомнил: {name} 📍"
LOCALITY_SAVED_TOAST = "Запомнил: {name}"

ASK_INTERESTS = (
    "Что тебе интересно? Отметь всё, что нравится, — так подборки будут точнее. Можно пропустить."
)
INTERESTS_DONE_BUTTON = "Готово"
INTERESTS_SAVED = "Готово! Вот что я умею 👇"
INTEREST_ON = "✅ {name}"
INTEREST_OFF = "{emoji} {name}"

# --- Подборки «Сегодня / Выходные / По Пушкинской» (§12) ---

FEED_TITLES = {
    "today": "Сегодня рядом с тобой",
    "weekend": "На выходных рядом с тобой",
    "pushkin": "По Пушкинской карте рядом с тобой",
}
FEED_HEADER = "{title} ({place}, до {radius} км):"
FEED_EMPTY = (
    "{title}: в радиусе {radius} км ничего не нашёл 😔\n"
    "Попробуй увеличить радиус в настройках или загляни в афишу."
)
FEED_DEMO_NOTE = "🧪 Демо-данные — показываем, как будет выглядеть афиша."
FEED_ITEM = "{n}. {when} · {title}{demo}\n   {place}{distance} · {price}{pushkin}"
FEED_ITEM_DEMO = " [демо]"
FEED_DETAILS_BUTTON = "{n}. Подробнее"
FEED_SAVE_BUTTON = "⭐ Пойду"
FEED_MORE_BUTTON = "Ещё"
FEED_ALL_BUTTON = "Все в приложении"
FEED_WIDEN_BUTTON = "Расширить до {radius} км"
FEED_EXPIRED_TOAST = "Подборка устарела, открой её заново"
NEED_LOCALITY = "Сначала скажи, где ты живёшь — подберу события рядом."

PRICE_FREE = "бесплатно"
PRICE_DONATION = "донат"
PRICE_FROM = "от {price} ₽"
PRICE_EXACT = "{price} ₽"
PRICE_UNKNOWN = "цена уточняется"
PUSHKIN_MARK = " · 💳"
DISTANCE = " · {km} км"

SAVED_TOAST = "Добавил в «Мои Пойду» ⭐"
UNSAVED_TOAST = "Убрал из «Мои Пойду»"

# --- Мои «Пойду» ---

SAVED_HEADER = "Твои «Пойду»:"
SAVED_EMPTY = "Пока пусто. Жми «⭐ Пойду» в подборках — событие появится здесь."
SAVED_UNSAVE_BUTTON = "✖ {n}. Не пойду"

# --- Настройки (FR-ONB-4, FR-ONB-5) ---

SETTINGS = (
    "Настройки:\n"
    "📍 Место: {place}\n"
    "📏 Радиус: {radius} км\n"
    "❤️ Интересы: {interests}\n"
    "🔔 Напоминания: {reminders} · Дайджест: {digest}"
)
SETTINGS_NO_PLACE = "не выбрано"
SETTINGS_NO_INTERESTS = "не выбраны"
SETTINGS_ON = "вкл"
SETTINGS_OFF = "выкл"
SETTINGS_PLACE_BUTTON = "📍 Сменить место"
SETTINGS_RADIUS_BUTTON = "{radius} км"
SETTINGS_RADIUS_CURRENT = "• {radius} км •"
SETTINGS_INTERESTS_BUTTON = "❤️ Интересы"
SETTINGS_REMINDERS_BUTTON = "🔔 Напоминания: {state}"
SETTINGS_DIGEST_BUTTON = "📰 Дайджест: {state}"
SETTINGS_DELETE_BUTTON = "🗑 Удалить мои данные"
SETTINGS_SAVED_TOAST = "Сохранил"

DELETE_CONFIRM = (
    "Удалить твои данные? Сотрём профиль, место, интересы, «Пойду» и подписки. Отменить это нельзя."
)
DELETE_YES_BUTTON = "Да, удалить"
DELETE_NO_BUTTON = "Отмена"
DELETE_DONE = "Готово, твои данные удалены. Если вернёшься — просто нажми /start."
DELETE_CANCELLED_TOAST = "Ничего не удалил"

DEEPLINK_EVENT = "Открываю событие 👇"
DEEPLINK_ORG = "Открываю страницу организатора 👇"
DEEPLINK_DRAFT = "Твой черновик события готов к редактированию 👇"
DEEPLINK_INVITE = "Тебя пригласили в команду организатора 👇"
DEEPLINK_FEED = "Открываю подборку 👇"
DEEPLINK_OPEN_BUTTON = "Открыть"

ERROR = "Что-то пошло не так, попробуй ещё раз"

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WHEN = "{weekday} {date}, {time}"
