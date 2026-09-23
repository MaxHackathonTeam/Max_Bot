COMPOSE ?= docker compose
PROD = $(COMPOSE) -f compose.yaml -f compose.prod.yaml
BACKEND = cd backend &&

.PHONY: up down logs test lint fmt migrate seed openapi eval deploy build-time

up:  ## Собрать и поднять всё локально
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

test:  ## Тесты бэкенда и фронтенда
	$(BACKEND) uv run pytest
	cd frontend && npm test

lint:  ## ruff + mypy + eslint + tsc
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	cd frontend && npm run lint && npm run typecheck

fmt:
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .

migrate:  ## alembic upgrade head в контейнере
	$(COMPOSE) run --rm migrate

seed:  ## Загрузка демо-данных (этап 2)
	@echo "seed: демо-данные появятся на этапе 2" && exit 1

openapi:  ## Экспорт OpenAPI в openapi.yaml (этап 6 — полноценный)
	@echo "openapi: экспорт в openapi.yaml будет добавлен вместе с эндпоинтами (этапы 1–6)" && exit 1

eval:  ## Оценка качества LLM (этап 5)
	@echo "eval: наборы и скрипт появятся на этапе 5" && exit 1

deploy:  ## На сервере: обновить код и перезапустить прод
	git pull --ff-only
	$(PROD) up -d --build --remove-orphans

build-time:  ## Замер времени сборки (лимит 5 мин)
	@start=$$(date +%s); $(COMPOSE) build --no-cache || exit 1; \
	 dur=$$(( $$(date +%s) - start )); echo "build: $${dur}s"; test $$dur -le 300
