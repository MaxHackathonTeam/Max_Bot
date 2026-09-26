# Афиша рядом

Бот и мини-приложение в MAX для поиска событий рядом с небольшими городами и сёлами. Пользователь выбирает населённый пункт и интересы, открывает ленту, сохраняет событие и получает напоминание. Организатор создаёт событие из формы или текста, после чего оно проходит автоматическую модерацию.

## Архитектура

FastAPI API и webhook бота, arq worker, PostgreSQL 16 + PostGIS, Redis 7, React 18 + TypeScript мини-приложение за nginx, Caddy в production. Изменения сущностей пишутся в `audit_log`; официальные и community события выдаются раздельно.

## Запуск

Требуется Docker Compose v2.24+:

```bash
cp .env.example .env
docker compose up --build
```

Мини-приложение: `http://localhost:8080`, API: `http://localhost:8000`; PostgreSQL и Redis доступны только внутри Compose. `make migrate` применяет миграции, `make seed` загружает демо-набор. Для разработки нужны Python 3.12 + uv и Node.js 22; зависимости зафиксированы в `backend/uv.lock` и `frontend/package-lock.json`.

## Переменные окружения

Полный список в [`.env.example`](.env.example). Секреты MAX, GigaChat, DaData и PRO.Культура.РФ задаются только в `.env`. `DEV_AUTH=1` допустим только локально. `REVIEW_MODE=1` включает `/api/v1/auth/review-login`; JSON `REVIEW_ACCOUNTS` задаётся человеком, в репозитории паролей нет. `OFFLINE_MODE=1` переключает внешние интеграции на фикстуры и кэш.

## Внешние сервисы

MAX Bot API нужен для реального бота и webhook; GigaChat — для извлечения и модерации; DaData — для реестра организаций; PRO.Культура.РФ — для импорта. Они не поднимаются Docker Compose. Без ключей локальный API работает с fallback и демо-фикстурами, а модерация остаётся в очереди.

## Данные и резервные копии

Демо-данные находятся в `data/seed/` и имеют `source=demo`/`trust_tier=demo` с видимым бейджем. Резервная копия: `DATABASE_URL=... BACKUP_DIR=./backups make backup`; хранятся последние 7 дней.

## Сценарий проверки

1. Запусти Compose и проверь `/health`, `/ready`.
2. Открой `http://localhost:8080`, войди через `DEV_AUTH=1`, прими условия, выбери населённый пункт и интересы.
3. Проверь вкладки ленты, радиус, дату, цену, Пушкинскую карту, карточку и «Пойду».
4. Открой настройки и удаление данных; создай черновик организатора и отправь на проверку.
5. Для API используй [DATA-API.yaml](DATA-API.yaml), для ручного прогона — [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md).

Ошибки имеют `error.code/message/details`, сетевые сбои показывают «Повторить», бот отвечает fallback-текстом, события сообщества не попадают в официальную ленту.

## Проверки и материалы сдачи

```bash
make lint
make test
make openapi
make eval
cd backend && uv run pip-audit
cd frontend && npm audit --audit-level=high
```

`openapi.yaml` и `DATA-API.yaml` описывают API. Адрес production API, токен бота и review-пароли передаются жюри отдельно.

## Ограничения

Продакшен требует публичного HTTPS, токена MAX и ключей внешних сервисов. Геолокация в WebView может быть недоступна, поэтому есть выбор населённого пункта. Продажа билетов, встроенная карта, парсинг сайтов и Kubernetes не входят в MVP. Адреса демо-площадок приблизительные.

## Возможности MAX

Используются `startapp` диплинки, `request_geo_location`, проверяемый `request_contact`, `shareMaxContent` с копированием ссылки, BackButton, haptics и уведомления/дайджест от бота.

## Остановка

```bash
docker compose down
docker compose up --build
```
