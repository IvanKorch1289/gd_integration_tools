from aioredis import Redis

from gd_advanced_tools.core.settings import settings


class RedisClient:
    def __init__(self):
        self._client = None

    async def init(self) -> None:
        self._client = Redis(
            address=(settings.redis_settings.host, settings.redis_settings.port),
            db=settings.redis_settings.db,
            password=settings.redis_settings.password,
            encoding=settings.redis_settings.encoding,
            decode_responses=settings.redis_settings.decode_responses,
        )

    async def get_client(self) -> Redis:
        if self._client is None:
            await self.init()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            await self._client.wait_closed()


redis = RedisClient()
