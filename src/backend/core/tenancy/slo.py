"""Multi-tenant SLO — Service Level Objectives per tenant (S178 #4).

Лёгкий atomic модуль для per-tenant SLO (latency, availability, error rate).
Дефолтные значения — production-grade для всех тенантов без per-tenant
override. Per-tenant overrides — через ``TenantSLO.for_tenant(tenant_id)``
с lookup из settings / Redis (future extension).

S178 #4 (lockjaw-vision-rocket.md): per-tenant SLO/quotas. Этот модуль
предоставляет dataclass + factory + ``evaluate()`` для проверки метрик
против SLO порогов. Используется в observability/alerts pipeline.

Пример::

    slo = TenantSLO.default()
    evaluation = slo.evaluate(latency_p99_ms=200.0, error_rate=0.005)
    if not evaluation.within_slo:
        logger.warning(\"Tenant exceeded SLO\", extra=evaluation.to_log_dict())

Scope: PURE-evaluator (no I/O, no Redis). Для runtime metrics tracking
используйте существующий ``QuotaTracker`` (Redis-backed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ("SLOEvaluation", "TenantSLO")


@dataclass(slots=True, frozen=True)
class TenantSLO:
    """Per-tenant Service Level Objectives (SLO).

    Attributes:
        latency_p99_ms: P99 latency budget в миллисекундах. Default 500ms
            (production baseline).
        availability_target: Доля uptime (``0.0`` … ``1.0``). Default
            ``0.999`` (99.9% = три девятки, ≈8.7h downtime/year).
        error_rate_target: Максимальная доля errors (``0.0`` … ``1.0``).
            Default ``0.01`` (1%).
    """

    latency_p99_ms: float = 500.0
    availability_target: float = 0.999
    error_rate_target: float = 0.01

    @classmethod
    def default(cls) -> "TenantSLO":
        """Production baseline SLO (для всех тенантов без override)."""
        return cls()

    @classmethod
    def for_tenant(cls, tenant_id: str | None) -> "TenantSLO":
        """Вернуть SLO для конкретного тенанта.

        Args:
            tenant_id: ID тенанта (``None`` → default SLO).

        Returns:
            :class:`TenantSLO` для тенанта. В текущей версии — всегда
            default; в S179+ будет lookup из ``TenantSettings.tenant_slo``
            или Redis (per-tenant overrides).
        """
        # S178 #4: только default. Per-tenant overrides — S179+ extension.
        return cls.default()

    def evaluate(
        self,
        *,
        latency_p99_ms: float | None = None,
        availability: float | None = None,
        error_rate: float | None = None,
    ) -> "SLOEvaluation":
        """Проверить метрики против SLO порогов.

        Args:
            latency_p99_ms: Наблюдаемый P99 latency в ms (если известен).
            availability: Наблюдаемая доля uptime ``0.0`` … ``1.0``.
            error_rate: Наблюдаемая доля errors ``0.0`` … ``1.0``.

        Returns:
            :class:`SLOEvaluation` с breakdown по каждой метрике +
            aggregate ``within_slo`` (True только если все available
            метрики within budget).
        """
        latency_ok: bool | None = None
        if latency_p99_ms is not None:
            latency_ok = latency_p99_ms <= self.latency_p99_ms

        availability_ok: bool | None = None
        if availability is not None:
            availability_ok = availability >= self.availability_target

        error_rate_ok: bool | None = None
        if error_rate is not None:
            error_rate_ok = error_rate <= self.error_rate_target

        # Aggregate: только если все available True.
        checks = [c for c in (latency_ok, availability_ok, error_rate_ok) if c is not None]
        within_slo = all(checks) if checks else True

        return SLOEvaluation(
            tenant_slo=self,
            latency_p99_ms=latency_p99_ms,
            latency_ok=latency_ok,
            availability=availability,
            availability_ok=availability_ok,
            error_rate=error_rate,
            error_rate_ok=error_rate_ok,
            within_slo=within_slo,
        )


@dataclass(slots=True, frozen=True)
class SLOEvaluation:
    """Результат evaluate() — per-metric breakdown + aggregate verdict.

    Attributes:
        tenant_slo: Reference на применённый :class:`TenantSLO`.
        latency_p99_ms: Наблюдаемый P99 latency (``None`` если не замеряли).
        latency_ok: ``True`` если latency within budget.
        availability: Наблюдаемая availability (``None`` если не замеряли).
        availability_ok: ``True`` если availability >= target.
        error_rate: Наблюдаемый error rate (``None`` если не замеряли).
        error_rate_ok: ``True`` если error_rate <= target.
        within_slo: ``True`` если все замерянные метрики within budget.
    """

    tenant_slo: TenantSLO
    latency_p99_ms: float | None = None
    latency_ok: bool | None = None
    availability: float | None = None
    availability_ok: bool | None = None
    error_rate: float | None = None
    error_rate_ok: bool | None = None
    within_slo: bool = True

    def to_log_dict(self) -> dict[str, object]:
        """Сериализация для structured log.

        Returns:
            Dict с flat keys для structlog (``slo.*`` префикс).
        """
        return {
            "slo.latency_p99_ms": self.latency_p99_ms,
            "slo.latency_ok": self.latency_ok,
            "slo.availability": self.availability,
            "slo.availability_ok": self.availability_ok,
            "slo.error_rate": self.error_rate,
            "slo.error_rate_ok": self.error_rate_ok,
            "slo.within_slo": self.within_slo,
            "slo.target_latency_p99_ms": self.tenant_slo.latency_p99_ms,
            "slo.target_availability": self.tenant_slo.availability_target,
            "slo.target_error_rate": self.tenant_slo.error_rate_target,
        }