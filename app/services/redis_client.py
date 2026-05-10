"""
Cliente Redis async — singleton compartido por toda la app.
"""
import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()

# from_url crea internamente un ConnectionPool reutilizable.
# decode_responses=True → str en lugar de bytes (más cómodo para keys/counters).
redis_client: redis.Redis = redis.from_url(
    _settings.redis_url, decode_responses=True
)


async def get_redis() -> redis.Redis:
    """Dependencia FastAPI: devuelve el cliente Redis singleton."""
    return redis_client
