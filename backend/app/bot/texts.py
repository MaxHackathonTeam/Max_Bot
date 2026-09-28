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
    "/org — кабинет организатора\n"
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

# --- Организатор и верификация (§5.3, §12) ---

ORG_MENU = (
    "Кабинет организатора — в приложении: организации, события, команда и проверка.\n"
    "Без организации тоже можно публиковать — в разделе «От жителей» после проверки."
)
ORG_OPEN_BUTTON = "🏛 Кабинет организатора"
ORG_NEW_EVENT_BUTTON = "➕ Новое событие"

PHONE_REQUEST = (
    "Чтобы проверить организацию «{org}», подтверди свой номер телефона кнопкой ниже. "
    "Сохраню только отметку «телефон подтверждён», сам номер — нет."
)
PHONE_REQUEST_BUTTON = "📱 Подтвердить телефон"
PHONE_CONFIRMED = "Телефон подтверждён ✅ Остальные шаги проверки — в приложении."
PHONE_NO_REQUEST = "Сейчас нет заявки на проверку организации — телефон не нужен."
PHONE_BAD_SIGNATURE = "Не удалось проверить контакт. Нажми кнопку «📱 Подтвердить телефон» ещё раз."
PHONE_NOT_OWN = "Нужен твой собственный контакт — нажми кнопку «📱 Подтвердить телефон»."

VERIFY_DONE = "🎉 Организация «{org}» проверена! Теперь события сразу попадают в «Официальные»."
VERIFY_STEP_FAILED = (
    "Проверка организации «{org}» пока не пройдена:\n{reasons}\n\n"
    "Исправь и нажми «Проверить снова» в приложении (не чаще раза в 10 минут)."
)
VERIFY_MANUAL_QUEUED = "Заявка на проверку «{org}» передана администратору. Сообщу о решении."
VERIFY_REJECTED = "Проверка организации «{org}» отклонена: {reason}"
VERIFY_REVOKED = (
    "Проверка организации «{org}» отозвана администратором. "
    "События организации теперь показываются в «От жителей»."
)
INVITE_VERIFIED = "Организация «{org}» проверена по приглашению ✅"

# --- Модерация событий (§6) ---

EVENT_PUBLISHED = "✅ Событие «{title}» опубликовано."
EVENT_REJECTED = "❌ Событие «{title}» не опубликовано: {reason}"
EVENT_HIDDEN = "⚠️ Событие «{title}» временно скрыто до проверки администратором. Причина: {reason}"
EVENT_RETURNED = "✏️ Событие «{title}» вернули на доработку: {reason}\nИсправь и отправь снова."
EVENT_PENDING_REVIEW = "Событие «{title}» на проверке — сообщу, когда опубликую."
EVENT_OPEN_BUTTON = "Открыть"
MODERATION_DEFAULT_REASON = "нарушает правила площадки"
REPORTS_HIDDEN_REASON = "несколько жалоб от пользователей"

# --- Очередь админа (§6 п. 5) ---

ADMIN_ONLY = "Эта команда только для администраторов."
QUEUE_EMPTY = "Очередь пуста 🎉"
QUEUE_HEADER = "В очереди: событий — {events}, заявок на проверку — {verifications}."
QUEUE_EVENT = "📝 Событие #{id} · {status} · {tier}\n«{title}»\n{org}{when}\n{reason}"
QUEUE_VERIFICATION = "🏛 Заявка #{id} · {method}\n«{org}» · ИНН {inn}\n{steps}"
QUEUE_APPROVE_BUTTON = "✅ Одобрить"
QUEUE_REJECT_BUTTON = "❌ Отклонить"
QUEUE_HIDE_BUTTON = "🙈 Скрыть"
QUEUE_REVOKE_BUTTON = "⛔ Отозвать верификацию"
QUEUE_OPEN_BUTTON = "Открыть"
QUEUE_ASK_REASON = "Напиши причину отказа одним сообщением (её увидит автор)."
QUEUE_REASON_TOO_SHORT = "Причина слишком короткая — напиши хотя бы пару слов."
QUEUE_DONE_TOAST = "Готово"
QUEUE_ALREADY_TOAST = "Уже решено"
QUEUE_DECIDED = "Решение по #{id}: {verdict}"
QUEUE_VERDICTS = {
    "approve": "одобрено",
    "reject": "отклонено",
    "hide": "скрыто",
    "revoke": "верификация отозвана",
}
QUEUE_REVOKE_REASON = "отозвано администратором"
QUEUE_NO_STEPS = "шаги ещё не пройдены"


# --- Вход на сайте через MAX --------------------------------------------------------------

WEB_LOGIN_CONFIRM = (
    "Подтвердить вход на сайте «Афиша рядом»?\n\n"
    "Код: {code}. Если ты не запрашивал вход — просто не нажимай кнопку."
)
WEB_LOGIN_BUTTON = "Подтвердить вход"
WEB_LOGIN_DONE_TOAST = "Готово — вернись на сайт"
WEB_LOGIN_EXPIRED = "Код истёк или уже использован. Запроси новый на сайте."
WEB_LOGIN_UNAVAILABLE = "Вход на сайте сейчас недоступен, попробуй позже."
