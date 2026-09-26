from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.events import router as events_router
from app.api.v1.geo import router as geo_router
from app.api.v1.imports import router as imports_router
from app.api.v1.me import router as me_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.orgs import invites_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1.search import router as search_router
from app.api.v1.venues import router as venues_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(me_router)
router.include_router(imports_router)
router.include_router(geo_router)
router.include_router(events_router)
router.include_router(orgs_router)
router.include_router(search_router)
router.include_router(notifications_router)
router.include_router(invites_router)
router.include_router(venues_router)
router.include_router(admin_router)
