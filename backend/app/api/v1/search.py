"""Поиск фразой и черновики из текста."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import AuthDep, SessionDep
from app.llm.runner import LlmRunner
from app.schemas.manage import EventManage
from app.services import drafts, event_editor, search_parse

router = APIRouter(tags=["search"])


class PhraseIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DraftIn(PhraseIn):
    org_id: int | None = None


def _llm(request: Request) -> LlmRunner | None:
    runner: LlmRunner | None = getattr(request.app.state, "llm", None)
    return runner


@router.post("/search/parse", summary="Фраза → фильтры, fallback на FTS")
async def parse_phrase(
    body: PhraseIn, auth: AuthDep, session: SessionDep, request: Request
) -> search_parse.ParsedSearch:
    return await search_parse.parse(session, body.text, _llm(request))


@router.post(
    "/drafts/from-text",
    response_model=EventManage,
    status_code=201,
    summary="Черновик из текста или пересланного поста",
)
async def from_text(
    body: DraftIn, auth: AuthDep, session: SessionDep, request: Request
) -> EventManage:
    event = await drafts.create_from_text(session, auth.user, body.text, body.org_id, _llm(request))
    return await event_editor.manage_view(session, auth.user, event.id)


@router.get("/drafts/{event_id}", response_model=EventManage, summary="Черновик для автора")
async def get_draft(event_id: int, auth: AuthDep, session: SessionDep) -> EventManage:
    return await event_editor.manage_view(session, auth.user, event_id)
