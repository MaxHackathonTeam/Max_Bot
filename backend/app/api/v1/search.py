"""Поиск фразой и черновики из текста."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AuthDep, SessionDep
from app.schemas.manage import EventManage
from app.services import drafts, event_editor, search_parse

router = APIRouter(tags=["search"])


class PhraseIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DraftIn(PhraseIn):
    org_id: int | None = None


@router.post(
    "/search/parse",
    summary="Фраза → фильтры по правилам, остаток — в полнотекстовый поиск. Без авторизации",
)
async def parse_phrase(body: PhraseIn, session: SessionDep) -> search_parse.ParsedSearch:
    return await search_parse.parse(session, body.text)


@router.post(
    "/drafts/from-text",
    response_model=EventManage,
    status_code=201,
    summary="Черновик из текста или пересланного поста",
)
async def from_text(body: DraftIn, auth: AuthDep, session: SessionDep) -> EventManage:
    event = await drafts.create_from_text(session, auth.user, body.text, body.org_id)
    return await event_editor.manage_view(session, auth.user, event.id)


@router.get("/drafts/{event_id}", response_model=EventManage, summary="Черновик для автора")
async def get_draft(event_id: int, auth: AuthDep, session: SessionDep) -> EventManage:
    return await event_editor.manage_view(session, auth.user, event_id)
