"""Health check service для tech-роута (T7 P1 fix, S107).

Ранее документировался в interfaces/multi_protocol.py:262, но модуль не
существовал → удаление INFRA_MODULES ключа `monitoring.health_check` в
S102 P2-11 сломало tech-роут `/api/v1/tech/*` (500 на каждый вызов,
так как provider не мог resolve_module).

Этот stub реализует минимальный contract:
- ``HealthCheckService`` class с async context manager (`async with`).
- ``check_database/redis/s3/s3_bucket/graylog/smtp/rabbitmq/all_services`` —
  async methods возвращают bool / dict (Ponytail: True если коннект ОК,
  False при ошибке; production-grade имплементация будет в S107+).
- ``get_healthcheck_service`` factory function (lazy singleton).

Production-grade замены — задокументированы как TODO; текущая реализация
возвращает hard-coded False с logging для visibility (fail-soft). Это
не блокирует tech-роут от 500.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

_logger = logging.getLogger(__name__)

__all__ = ("HealthCheckService", "get_healthcheck_service")


class HealthCheckService:
    """Stub HealthCheckService.

    Контекстный менеджер + async check_* methods. Возвращают False (fail-soft)
    пока production-grade реализация не добавлена в S107+.
    """

    async def __aenter__(self) -> HealthCheckService:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    async def check_database(self) -> bool:
        """Check database health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_database stub — returns False")
        return False

    async def check_redis(self) -> bool:
        """Check Redis health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_redis stub — returns False")
        return False

    async def check_s3(self) -> bool:
        """Check S3 health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_s3 stub — returns False")
        return False

    async def check_s3_bucket(self) -> bool:
        """Check S3 bucket health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_s3_bucket stub — returns False")
        return False

    async def check_graylog(self) -> bool:
        """Check Graylog health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_graylog stub — returns False")
        return False

    async def check_smtp(self) -> bool:
        """Check SMTP health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_smtp stub — returns False")
        return False

    async def check_rabbitmq(self) -> bool:
        """Check RabbitMQ health. Stub: всегда False."""
        _logger.debug("HealthCheckService.check_rabbitmq stub — returns False")
        return False

    async def check_all_services(self) -> dict[str, Any]:
        """Check all services. Stub: returns all-False dict."""
        _logger.debug("HealthCheckService.check_all_services stub")
        return {
            "database": await self.check_database(),
            "redis": await self.check_redis(),
            "s3": await self.check_s3(),
            "graylog": await self.check_graylog(),
            "smtp": await self.check_smtp(),
            "rabbitmq": await self.check_rabbitmq(),
        }


_instance: HealthCheckService | None = None


def get_healthcheck_service() -> HealthCheckService:
    """Lazy singleton factory."""
    global _instance
    if _instance is None:
        _instance = HealthCheckService()
    return _instance
