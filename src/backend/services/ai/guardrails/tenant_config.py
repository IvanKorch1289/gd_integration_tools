"""Per-tenant guardrails configuration (Sprint 11 K1 W2)."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ("GuardrailsConfig", "GuardrailsThresholds")


@dataclass(frozen=True, slots=True)
class GuardrailsThresholds:
    """Пороги срабатывания провайдеров на одном tenant.

    Attributes:
        lakera_threshold: Минимальный score Lakera Guard (0..1), при котором
            запрос блокируется (`flagged=True`). 0.0 — блокировать всё,
            1.0 — фактически отключить.
        rebuff_threshold: Аналогично для Rebuff prompt-injection detector.
    """

    lakera_threshold: float = 0.5
    rebuff_threshold: float = 0.7


@dataclass(frozen=True, slots=True)
class GuardrailsConfig:
    """Полная per-tenant конфигурация guardrails.

    Attributes:
        enabled_providers: Какие провайдеры активны для tenant'а
            (``{"lakera", "rebuff", "nemo"}`` подмножество).
        thresholds: Численные пороги.
        block_on_failure: ``True`` — при ошибке/timeout провайдера запрос
            блокируется fail-closed; ``False`` — fail-open (для warn-only).
    """

    enabled_providers: frozenset[str] = field(
        default_factory=lambda: frozenset(("lakera", "rebuff", "nemo"))
    )
    thresholds: GuardrailsThresholds = field(default_factory=GuardrailsThresholds)
    block_on_failure: bool = False


# Default — pass-through конфиг до явного override в tenant-settings.
_DEFAULT = GuardrailsConfig(
    enabled_providers=frozenset(),
    thresholds=GuardrailsThresholds(),
    block_on_failure=False,
)


def get_default_config() -> GuardrailsConfig:
    """Возвращает дефолтный конфиг (пустой ``enabled_providers``)."""
    return _DEFAULT
