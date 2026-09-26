COMPOSE ?= docker compose
PROD = $(COMPOSE) -f compose.yaml -f compose.prod.yaml
BACKEND = cd backend &&

.PHONY: up down logs test lint fmt migrate seed seed-gen openapi eval deploy build-time backup

up:  ## Собрать и поднять всё локально
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

# Тесты с БД: нужен Postgres+PostGIS, например
#   docker run -d --name afisha-testdb -p 55432:5432 -e POSTGRES_USER=afisha \
#     -e POSTGRES_PASSWORD=afisha postgis/postgis:16-3.4
TEST_DATABASE_URL ?= postgresql+asyncpg://afisha:afisha@localhost:55432/afisha

test:  ## Тесты бэкенда и фронтенда
	$(BACKEND) TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest
	cd frontend && npm test

lint:  ## ruff + mypy + eslint + tsc
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	cd frontend && npm run lint && npm run typecheck

fmt:
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .

migrate:  ## alembic upgrade head в контейнере
	$(COMPOSE) run --rm migrate

seed:  ## Загрузка/обновление демо-данных из data/seed (сеансы сдвигаются к сегодня)
	$(COMPOSE) run --rm -e SEED_DEMO=1 migrate python -m app.seed

seed-gen:  ## Пересобрать data/seed/events.json из шаблонов
	$(BACKEND) uv run python scripts/gen_demo_events.py

openapi:  ## Экспорт OpenAPI в openapi.yaml
	$(BACKEND) uv run python scripts/export_openapi.py

backup:  ## Резервная копия PostgreSQL, хранить 7 дней
	./backend/scripts/backup.sh

eval:  ## Оценка качества LLM (этап 5)
	$(BACKEND) uv run python scripts/eval.py

deploy:  ## На сервере: обновить код и перезапустить прод
	git pull --ff-only
	$(PROD) up -d --build --remove-orphans

build-time:  ## Замер времени сборки (лимит 5 мин)
	@start=$$(date +%s); $(COMPOSE) build --no-cache || exit 1; \
	 dur=$$(( $$(date +%s) - start )); echo "build: $${dur}s"; test $$dur -le 300
