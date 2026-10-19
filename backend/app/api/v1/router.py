from fastapi import APIRouter

from app.api.v1.routes import (
    assets,
    auth,
    health,
    maintenance,
    organization,
    procurement,
    reports,
    security_admin,
    verification,
    finance,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(security_admin.router)
router.include_router(organization.router)
router.include_router(assets.router)
router.include_router(procurement.router)
router.include_router(maintenance.router)
router.include_router(reports.router)
router.include_router(verification.router)
router.include_router(finance.router)

