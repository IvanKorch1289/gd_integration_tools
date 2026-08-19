"""Stub QuotasService skeleton (cycle 33 B-07).

Реальный billing backend не интегрирован — этот модуль существует как
контрактный placeholder, чтобы DI-провайдер
(:func:`src.backend.core.di.providers.billing.get_quotas_backend_provider`)
и :class:`QuotaCheckMiddleware` импортировали имена из канонического
места. До интеграции используйте :class:`NoOpBillingFacade`.
"""

from __future__ import annotations

from src.backend.core.auth.quotas_protocol import QuotasBackend

__all__ = ("QuotasService",)


class QuotasService:
    """Stub: real billing backend not yet integrated. See NoOpBillingFacade."""

    def __init__(self) -> None:
        """Бросает ``NotImplementedError`` — реальный backend не готов."""
        raise NotImplementedError(
            "QuotasService not yet implemented; use NoOpBillingFacade via "
            "src.backend.core.di.providers.billing.get_quotas_backend_provider()."
        )

    async def consume_request(self, tenant_id: str):  # pragma: no cover
        """Заглушка интерфейса; не должна вызываться."""
        raise NotImplementedError("QuotasService.consume_request is a stub")

    async def check_tokens(self, tenant_id: str, tokens: int):  # pragma: no cover
        """Заглушка интерфейса; не должна вызываться."""
        raise NotImplementedError("QuotasService.check_tokens is a stub")

    # Structural-typing marker: класс позиционируется как реализация Protocol,
    # но runtime-проверка isinstance(_Stub(), QuotasBackend) == False до тех
    # пор, пока экземпляр не создан (NotImplementedError на __init__).
    _protocol: QuotasBackend  # type: ignore[assignment]
