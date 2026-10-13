from fastapi import APIRouter, Depends
from src.presentation.api.v1 import health, auth, procurement, documents, guarantees, deadlines, settings, notifications, users
from src.presentation.auth_dependencies import get_current_user

api_router = APIRouter()

# Public routers
api_router.include_router(health.router)
api_router.include_router(auth.router)

# Everything below requires a valid access token for an active user.
protected = [Depends(get_current_user)]
api_router.include_router(procurement.router, dependencies=protected)
api_router.include_router(documents.router, dependencies=protected)
api_router.include_router(guarantees.router, dependencies=protected)
api_router.include_router(deadlines.router, dependencies=protected)
api_router.include_router(settings.router, dependencies=protected)
api_router.include_router(notifications.router, dependencies=protected)
api_router.include_router(users.router, dependencies=protected)
