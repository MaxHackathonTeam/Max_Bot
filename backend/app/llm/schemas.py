"""Схемы строгих JSON-ответов LLM (§6, §5.3 B.3)."""

from typing import Literal

from pydantic import BaseModel, Field

ModerationCategory = Literal[
    "spam",
    "ads",
    "fraud",
    "insult",
    "adult",
    "illegal",
    "politics_agitation",
    "not_event",
    "low_quality",
]


class ModerationVerdictOut(BaseModel):
    verdict: Literal["approve", "reject", "review"]
    confidence: float = Field(ge=0, le=1)
    categories: list[ModerationCategory] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list, max_length=10)
    fixed_category: str | None = None


class PageCheckOut(BaseModel):
    belongs: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = ""


class SearchFiltersOut(BaseModel):
    date: Literal["today", "tomorrow", "weekend"] | None = None
    free: bool = False
    pushkin: bool = False
    category: str | None = None
    locality: str | None = None
    remainder: str | None = None


class DraftFieldsOut(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = None
    locality: str | None = None
    starts_at: str | None = None
    price_type: Literal["free", "paid", "donation"] | None = None
    price_min: int | None = Field(default=None, ge=0)
    ticket_url: str | None = None


class EnrichmentOut(BaseModel):
    category: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    short_description: str | None = Field(default=None, max_length=200)
    indoor: Literal["indoor", "outdoor", "mixed", "unknown"] = "unknown"
    youth_score: float | None = Field(default=None, ge=0, le=1)
