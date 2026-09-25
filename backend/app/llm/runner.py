"""Вызов LLM со строгим JSON (§8): бюджет, 1 повтор при невалидном ответе, лог в llm_calls.

LLM только размечает и проверяет; при любой проблеме вызывающий берёт fallback.
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from app.db.session import SessionMaker
from app.integrations.gigachat import LlmClient, LlmUnavailable
from app.llm.prompts import load_prompt
from app.models.system import LlmCall

log = structlog.get_logger(__name__)

Status = Literal["ok", "invalid", "unavailable"]
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


@dataclass(frozen=True)
class LlmJson[T: BaseModel]:
    status: Status
    value: T | None
    prompt_version: str
    model: str | None


def extract_json(text: str) -> str:
    """JSON-объект из ответа: без ```-ограждений и текста вокруг."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return cleaned[start : end + 1] if start != -1 and end > start else cleaned


class LlmRunner:
    def __init__(self, llm: LlmClient | None, db: SessionMaker, daily_budget: int) -> None:
        self._llm = llm
        self._db = db
        self._budget = daily_budget

    @property
    def available(self) -> bool:
        return self._llm is not None

    async def _spent_today(self) -> int:
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._db() as session:
            spent = await session.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            func.coalesce(LlmCall.tokens_in, 0)
                            + func.coalesce(LlmCall.tokens_out, 0)
                        ),
                        0,
                    )
                ).where(LlmCall.created_at >= today)
            )
        return int(spent or 0)

    async def _log(self, call: LlmCall) -> None:
        async with self._db() as session:
            session.add(call)
            await session.commit()

    async def run_json[T: BaseModel](
        self, purpose: str, prompt_name: str, schema: type[T], **variables: object
    ) -> LlmJson[T]:
        prompt = load_prompt(prompt_name)
        if self._llm is None:
            return LlmJson("unavailable", None, prompt.version, None)
        if await self._spent_today() >= self._budget:
            log.warning("llm_budget_exceeded", purpose=purpose)
            return LlmJson("unavailable", None, prompt.version, self._llm.model)
        messages = prompt.messages(**variables)
        for attempt in range(2):
            started = time.perf_counter()
            call = LlmCall(
                purpose=purpose, model=self._llm.model, prompt_version=prompt.version, ok=False
            )
            try:
                result = await self._llm.chat(messages)
            except LlmUnavailable as exc:
                call.latency_ms = round((time.perf_counter() - started) * 1000)
                call.error = str(exc)[:500]
                await self._log(call)
                log.warning("llm_unavailable", purpose=purpose, error=type(exc).__name__)
                return LlmJson("unavailable", None, prompt.version, self._llm.model)
            call.latency_ms = round((time.perf_counter() - started) * 1000)
            call.tokens_in, call.tokens_out, call.model = (
                result.tokens_in,
                result.tokens_out,
                result.model,
            )
            try:
                value = schema.model_validate(json.loads(extract_json(result.text)))
            except (ValueError, ValidationError) as exc:
                call.error = f"invalid_json: {type(exc).__name__}"
                await self._log(call)
                log.info("llm_invalid_json", purpose=purpose, attempt=attempt)
                continue
            call.ok = True
            await self._log(call)
            return LlmJson("ok", value, prompt.version, result.model)
        return LlmJson("invalid", None, prompt.version, self._llm.model)
