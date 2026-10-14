from fastapi import APIRouter

from app.api.v1.routes import assets, health, organization

router = APIRouter()
router.include_router(health.router)
router.include_router(organization.router)
router.include_router(assets.router)
