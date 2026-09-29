"""Диагностика бота MAX — обёртка над app.bot.doctor (логика живёт в образе api).

Локально (из корня репозитория, .env рядом):
    cd backend && uv run python ../tools/bot_doctor.py [--fix]
На сервере — внутри контейнера:
    docker compose -f compose.yaml -f compose.prod.yaml exec api python -m app.bot.doctor
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.bot.doctor import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
