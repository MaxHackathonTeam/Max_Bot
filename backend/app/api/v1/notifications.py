from fastapi import APIRouter

from app.api.deps import AuthDep, SessionDep
from app.models.engagement import Subscription
from app.models.enums import SubscriptionKind
from app.services import audit

router = APIRouter(prefix="/orgs", tags=["notifications"])


@router.post("/{org_id}/subscribe", status_code=204)
async def subscribe(org_id: int, auth: AuthDep, session: SessionDep) -> None:
    await session.merge(
        Subscription(user_id=auth.user.id, org_id=org_id, kind=SubscriptionKind.organization)
    )
    await audit.record(
        session,
        action="org.subscribe",
        entity_type="organization",
        entity_id=org_id,
        actor_user_id=auth.user.id,
        diff={"subscribed": True},
    )
    await session.commit()


@router.delete("/{org_id}/subscribe", status_code=204)
async def unsubscribe(org_id: int, auth: AuthDep, session: SessionDep) -> None:
    from sqlalchemy import delete

    await session.execute(
        delete(Subscription).where(
            Subscription.user_id == auth.user.id,
            Subscription.org_id == org_id,
            Subscription.kind == SubscriptionKind.organization,
        )
    )
    await audit.record(
        session,
        action="org.unsubscribe",
        entity_type="organization",
        entity_id=org_id,
        actor_user_id=auth.user.id,
        diff={"subscribed": False},
    )
    await session.commit()
