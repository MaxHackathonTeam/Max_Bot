# Афиша рядом

Бот и мини-приложение в MAX для поиска и публикации событий в малых городах и сёлах.
Хакатон MAX, трек «Досуг и развлечения».

> **Статус:** каркас (этап 0). Разделы ниже будут заполнены по мере разработки.

## Назначение

_TODO (этап 6)._ Одна лента событий «рядом со мной» с радиусом по соседним населённым пунктам, фильтр «Пушкинская карта», напоминания и дайджест в чате; быстрая публикация событий организаторами.

## Основной сценарий

_TODO (этап 6)._

## Архитектура

_TODO (этап 6)._ Кратко: FastAPI (API + webhook бота) · arq-воркер · PostgreSQL 16 + PostGIS · Redis 7 · React-мини-апп за nginx · Caddy в проде.

## Быстрый запуск (Docker)

```bash
cp .env.example .env   # можно не заполнять: без токенов работает API и мини-апп в браузере
docker compose up --build
```

Проверка:

```bash
curl localhost:8000/health    # {"status":"ok"}
curl localhost:8000/ready     # готовность БД и Redis
open http://localhost:8080    # мини-апп (заглушка)
```

Локальный polling бота (без публичного HTTPS): `docker compose --profile local up --build`.

## Параметры и переменные окружения

Полный список — в [`.env.example`](.env.example). _TODO (этап 6): таблица с описанием._

## Порты

| Порт | Сервис |
|---|---|
| 8080 | мини-апп (nginx), `/api/*` проксируется в API |
| 8000 | API напрямую |
| 5432, 6379 | не публикуются наружу |

## Зависимости

- Docker с Compose v2.24+.
- Для разработки: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js 22.
- Зафиксированы в `backend/uv.lock` и `frontend/package-lock.json`.

## Внешние сервисы

_TODO (этап 6)._ Не поднимаются в Docker: MAX Bot API, GigaChat, DaData, PRO.Культура.РФ. Условия проверки без них — будут описаны здесь.

## Работа с данными

_TODO (этапы 1–2)._ Миграции: `make migrate`.

## Тестовые данные

_TODO (этап 2)._ Демо-данные помечены `source=demo` / `trust_tier=demo` и видимой плашкой «Демо-данные».

## Пошаговый сценарий проверки

_TODO (этап 6)._

## Ожидаемое поведение

_TODO (этап 6)._

## Известные ограничения

_TODO (этап 6)._

## Остановка и перезапуск

```bash
docker compose down        # остановить
docker compose down -v     # остановить и удалить данные
docker compose up --build  # перезапуск
```

## Разработка

```bash
make lint   # ruff, mypy, eslint, tsc
make test   # pytest, vitest
```

Pre-commit (ruff, gitleaks): `pipx install pre-commit && pre-commit install`.

## Возможности платформы MAX

_TODO (этап 6)._
