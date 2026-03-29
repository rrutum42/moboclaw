from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.session_config import session_settings

engine = create_async_engine(
    session_settings.database_url,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
