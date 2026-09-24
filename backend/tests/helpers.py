"""Общие константы и генераторы тестовых данных."""

import json
import random
import time
from typing import Any
from urllib.parse import urlencode

from app.core.security import sign

BOT_TOKEN = "test_bot_token_123"
JWT_SECRET = "test-jwt-secret-" + "x" * 32
WEBHOOK_SECRET = "test_webhook_secret"


def random_max_id() -> int:
    return random.randint(10**9, 10**12)


def make_init_data(
    user: dict[str, Any],
    *,
    token: str = BOT_TOKEN,
    auth_date: int | None = None,
    **extra: str,
) -> str:
    params = {
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        **extra,
    }
    params["hash"] = sign(params, token)
    return urlencode(params)
