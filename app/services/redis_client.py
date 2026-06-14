import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()

# from_url crea un ConnectionPool internamente. decode_responses=True nos da
# str en vez de bytes - más cómodo para counters y keys de rate limit.
redis_client: redis.Redis = redis.from_url(
    _settings.redis_url, decode_responses=True
)


async def get_redis() -> redis.Redis:
    return redis_client
