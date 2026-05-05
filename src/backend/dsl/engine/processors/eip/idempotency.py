import logging
from typing import Any, Callable

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = ("IdempotentConsumerProcessor",)


class IdempotentConsumerProcessor(BaseProcessor):
    """Idempotent Consumer — предотвращает повторную обработку.

    Использует Redis SET NX EX для дедупликации по ключу.
    Если сообщение уже обработано, Exchange останавливается.
    """

    def __init__(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "idempotent_consumer")
        self._key_expr = key_expression
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            dedup_key = f"idempotent:{self._key_expr(exchange)}"
            is_new = await redis_client.set_if_not_exists(
                key=dedup_key, value="1", ttl=self._ttl
            )
            if not is_new:
                _eip_logger.debug("Duplicate message filtered: key=%s", dedup_key)
                exchange.set_property("idempotent_duplicate", True)
                exchange.stop()
                return
        except Exception as exc:
            _eip_logger.warning("Idempotent check failed (proceeding): %s", exc)
