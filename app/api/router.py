"""Top-level API router."""

from fastapi import APIRouter

from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.contacts import router as contacts_router
from app.api.routes.health import router as health_router
from app.api.routes.templates import router as templates_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(contacts_router)
api_router.include_router(templates_router)
api_router.include_router(campaigns_router)
