from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.session_config import session_settings

engine = create_async_engine(
    session_settings.database_url,
    pool_pre_ping=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, connection_record) -> None:
    if engine.sync_engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
