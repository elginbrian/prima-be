from fastapi import APIRouter
from src.presentation.api.v1 import health, procurement, documents, guarantees, deadlines

api_router = APIRouter()

# Include all v1 routers
api_router.include_router(health.router)
api_router.include_router(procurement.router)
api_router.include_router(documents.router)
api_router.include_router(guarantees.router)
api_router.include_router(deadlines.router)
