from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException, RequestValidationError
from contextlib import asynccontextmanager
import os
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
    try:
        from src.application.use_cases.validation_use_cases import cleanup_stale_processing_validations
        cleaned = await cleanup_stale_processing_validations()
        if cleaned:
            logger.info(f"Marked {cleaned} stale background AI validation job(s) as failed on startup.")
    except Exception as exc:
        logger.warning(f"Skipped stale AI validation cleanup on startup: {exc}")
    try:
        from src.infrastructure.database import AsyncSessionLocal
        from src.presentation.api.v1.integrations import _load_synced_integration_config
        async with AsyncSessionLocal() as db:
            await _load_synced_integration_config(db)
    except Exception as exc:
        logger.warning(f"Skipped loading synced AI integration config on startup: {exc}")
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

    # Mount local uploads directory for local development & Docker volume
    uploads_dir = os.path.abspath(settings.local_storage_dir)
    os.makedirs(uploads_dir, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
