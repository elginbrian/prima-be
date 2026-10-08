from fastapi import APIRouter
from src.presentation.api.v1 import health, auth, procurement, documents, guarantees, deadlines, settings, notifications

api_router = APIRouter()

# Include all v1 routers
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(procurement.router)
api_router.include_router(documents.router)
api_router.include_router(guarantees.router)
api_router.include_router(deadlines.router)
api_router.include_router(settings.router)
api_router.include_router(notifications.router)
