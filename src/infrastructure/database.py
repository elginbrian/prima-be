from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from src.infrastructure.config import settings

Base = declarative_base()

# Import all models so that Base.metadata is aware of them
# Required for alembic migrations to work properly
from src.infrastructure.models import (  # noqa: E402, F401
    ProcurementRequestModel,
    ProcurementMilestoneModel,
    SettingsModel,
)


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """Dependency for getting database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database - schema is managed by Alembic migrations"""
    pass


async def close_db():
    """Close database connection"""
    await engine.dispose()
