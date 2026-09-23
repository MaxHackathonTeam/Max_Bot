# CLAUDE.md

Проект «Афиша рядом»: бот + мини-приложение в MAX для поиска и публикации событий в малых городах и сёлах. Хакатон, трек «Досуг и развлечения».

## Источники истины (в порядке приоритета)

1. `Досуг и развлечения.pdf` — условие трека, требования и ограничения.
2. `docs/TECHDOC.md` — техническое задание.
3. `docs/DEV_PLAN.md` — этапы работ и «Журнал».

`roadmap-max-hackathon.md` устарел — не использовать.

## Правила работы

- Работать **только в рамках текущего этапа** из `docs/DEV_PLAN.md`. В конце этапа прогнать гейт, отметить чек-боксы, дописать «Журнал».
- Приоритеты MoSCoW из §1.4 техдока: сначала M. W не делать никогда (платежи, парсинг сайтов и ВК, k8s, встроенная карта).
- **Секреты никогда не попадают в репозиторий** — только через env; `.env.example` без значений. Токен бота, ключи GigaChat, DaData, PRO.Культура — только в `.env`.
- Не выдумывать API MAX: сверяться с dev.max.ru и `github.com/max-messenger/api-schema`. Если что-то не подтверждено — сказать об этом, а не угадывать.
- LLM (GigaChat) не генерирует события и не формирует выдачу: только размечает, извлекает, модерирует. Всегда есть fallback.
- Демо-данные всегда помечены `source=demo` / `trust_tier=demo` и видимой плашкой.
- Ленты `official` и `community` не смешиваются.
- Каждое изменение сущностей пишется в `audit_log` через `services/audit.py`.
- Нужен секрет, доступ или решение человека — остановиться и сказать, что именно нужно.

## Стек

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, GeoAlchemy2, arq, httpx, structlog, uv.
- **Бот:** `maxapi` (github.com/max-messenger/max-botapi-python, зафиксирован по commit) или свой httpx-клиент. API `https://platform-api2.max.ru`, заголовок `Authorization: <token>`.
- **БД:** Postgres 16 + PostGIS + pg_trgm; Redis 7.
- **Frontend:** React 18 + TS + Vite, TanStack Query, React Router, MAX UI, MAX Bridge.
- **Инфраструктура:** Docker Compose (без k8s), Caddy в проде.

## Код

- Бизнес-логика — в `backend/app/services/`, роутеры тонкие. Проверка прав — в сервисном слое.
- Тексты бота — только в `backend/app/bot/texts.py`, на «ты».
- Ошибки API: `{"error": {"code", "message", "details"}}`, сообщения по-русски.
- Все внешние вызовы — с таймаутом, ретраями и логированием без ПДн.
- Время в БД — `timestamptz`; показ — в часовом поясе населённого пункта события.

## Команды

- `make up` — `docker compose up --build`
- `make test` · `make lint` · `make migrate` · `make seed` · `make openapi` · `make eval`
- Сборка должна укладываться в 5 минут.
