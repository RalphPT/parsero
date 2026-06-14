from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Railway entrega DATABASE_URL con prefijo postgresql:// (driver psycopg2).
# Como aquí usamos asyncpg, parchamos el prefijo cuando hace falta.
db_url = settings.database_url
if db_url.startswith("postgresql://"):
    db_url = "postgresql+asyncpg://" + db_url[len("postgresql://"):]
elif db_url.startswith("postgres://"):
    db_url = "postgresql+asyncpg://" + db_url[len("postgres://"):]

engine = create_async_engine(
    db_url,
    echo=settings.app_debug,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
