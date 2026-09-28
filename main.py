from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException, RequestValidationError
from contextlib import asynccontextmanager
from src.infrastructure.config import settings
from src.infrastructure.database import init_db, close_db
from src.presentation.api.v1 import api_router
from src.presentation.api.middleware.exception_handlers import (
    domain_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)
from src.domain.exceptions import DomainException
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    await init_db()
    logger.info("Prima Backend started.")
    yield
    await close_db()


def create_app() -> FastAPI:
    """Application factory"""
    app = FastAPI(
        title=settings.app_name,
        description="FastAPI Backend Service for Pertamina Procurement (Prima) - Clean Architecture",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # CORS Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Exception handlers
    app.add_exception_handler(DomainException, domain_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Include API routers
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
