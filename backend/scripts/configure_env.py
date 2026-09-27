"""Create a production .env interactively without echoing credentials."""

from __future__ import annotations

import getpass
import os
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def ask(label: str, default: str = "", *, secret: bool = False, required: bool = False) -> str:
    while True:
        suffix = " [обязательно]" if required and not default else ""
        prompt = f"{label}{suffix}" + (": " if not default else f" [{default}]: ")
        value = getpass.getpass(prompt) if secret else input(prompt)
        value = value or default
        if value or not required:
            return value
        print("Значение обязательно.")


def main() -> int:
    if TARGET.exists():
        print("Файл .env уже существует; остановка без изменений.", file=sys.stderr)
        return 1

    values: dict[str, str] = {}
    for line in TEMPLATE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    domain = ask("Домен без https://", "vse-vezde.ru", required=True)
    postgres_password = secrets.token_hex(32)
    app_password = secrets.token_hex(32)
    values.update(
        ENV="prod",
        DOMAIN=domain,
        PUBLIC_BASE_URL=f"https://{domain}",
        COMPOSE_FILE="compose.yaml:compose.prod.yaml",
        POSTGRES_PASSWORD=postgres_password,
        APP_DB_PASSWORD=app_password,
        MIGRATE_DATABASE_URL=(
            f"postgresql+asyncpg://afisha:{postgres_password}@db:5432/afisha"
        ),
        DATABASE_URL=(
            f"postgresql+asyncpg://afisha_app:{app_password}@db:5432/afisha"
        ),
        REDIS_URL="redis://redis:6379/0",
        JWT_SECRET=secrets.token_hex(32),
        MAX_WEBHOOK_SECRET=secrets.token_hex(24),
        BOT_MODE="webhook",
        DEV_AUTH="0",
        OFFLINE_MODE="0",
        SEED_DEMO="0",
    )

    values["MAX_BOT_TOKEN"] = ask("MAX Bot Token", secret=True, required=True)
    values["MAX_BOT_USERNAME"] = ask("MAX username бота (без @)", required=True)
    values["ADMIN_MAX_USER_IDS"] = ask("MAX ID администраторов (через запятую)")
    for key, label in (
        ("GIGACHAT_AUTH_KEY", "GigaChat Auth Key"),
        ("DADATA_API_KEY", "DaData API Key"),
        ("DADATA_SECRET_KEY", "DaData Secret Key"),
        ("PROCULTURE_API_KEY", "PRO.Культура API Key"),
    ):
        values[key] = ask(label, secret=True)

    lines = []
    for line in TEMPLATE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            lines.append(f"{key}={values.get(key, '')}")
        else:
            lines.append(line)
    lines.append("COMPOSE_FILE=" + values["COMPOSE_FILE"])

    fd = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as env_file:
        env_file.write("\n".join(lines) + "\n")
    print("Создан .env (права 600). Секреты не выводились.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
