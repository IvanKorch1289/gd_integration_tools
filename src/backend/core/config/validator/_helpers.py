"""Shared helpers для validator package (S52 W2 extraction).

Original validator.py defined эти symbols inline before the ConfigValidator
class. После decomp в 3 mixin files, shared symbols должны быть в
одном месте (избежать circular import между mixin ↔ __init__.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import Final

PRODUCTION_ENV: Final[str] = "production"
JWT_SECRET_MIN_LENGTH: Final[int] = 32

_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[str, tuple[str, ...]]] = {
    # supply_chain_strict_mode без supply_chain_finale_strict — WARNING (не блокирует startup)
    "supply_chain_strict_mode": ("supply_chain_finale_strict",)
}

_FEATURE_FLAG_DEPENDENCIES_CRITICAL: Final[Mapping[str, tuple[str, ...]]] = {
    # WAF zero-allowlist (при появлении) — CRITICAL security posture violation
    # "waf_strict_zero_allowlist": ("waf_outbound_via_facade",),  # раскомментировать когда флаг появится
    # outbound_metering_strict без per-host baseline = неверные rate-лимиты
    "outbound_metering_strict": ("metering_per_host",),
    # S45 W3 (TD-018 partial): lsp_server_strict без lsp_server = strict-mode
    # применяется к несуществующему pipeline → silent no-op (security audit
    # tooling gap).
    "lsp_server_strict": ("lsp_server",),
    # ai_prompt_sweep_strict без ai_prompt_sweep = prod sweep runs against
    # disabled sweep base (no actual enforcement).
    "ai_prompt_sweep_strict": ("ai_prompt_sweep",),
}

_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP: Final[frozenset[str]] = frozenset(
    {
        "supply_chain_finale_strict",
        "dsl_processor_registry_strict",
        "plugin_semver_strict",
        "tracing_baggage_strict",
        "perf_gate_strict",
        "processor_health_checks_strict",
        "dsl_linter_strict",
        "workflow_versioning_strict",
        "metrics_registry_strict",
        "task_registry_strict",
        "routes_capability_gate_strict",
        "routes_tenant_aware_strict",
        "call_function_whitelist_strict",
        "mcp_tools_input_schema_strict",
        "ai_cost_dashboard_strict",  # S45 W3 — добавлен после fix
    }
)


class ConfigSeverity(StrEnum):
    """Severity levels для ConfigViolation."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ConfigViolation:
    """Описание одного обнаруженного нарушения конфигурации.

    Атрибуты:
        severity: Уровень критичности (CRITICAL блокирует prod-стартап).
        code: Стабильный машиночитаемый код (для DoD грепа и алертов).
        message: Человекочитаемое описание нарушения на русском.
        field: Точка конфигурации, к которой относится нарушение
            (``"<settings>.<attribute>"``).
        recommendation: Рекомендуемое действие для оператора.
        context: Дополнительный контекст (текущее значение и т.п.).
    """

    severity: ConfigSeverity
    code: str
    message: str
    field: str
    recommendation: str
    context: dict[str, object] = dc_field(default_factory=dict)


class ProductionConfigError(RuntimeError):
    """Поднимается, когда конфигурация production-окружения содержит
    хотя бы одно :attr:`ConfigSeverity.CRITICAL` нарушение.

    lifespan-хук перехватывает эту ошибку и преобразует её в
    fail-fast завершение startup-а.
    """

    def __init__(self, violations: tuple[ConfigViolation, ...]) -> None:
        self.violations = violations
        super().__init__(
            "Конфигурация production-окружения содержит критические нарушения: "
            + "; ".join(f"[{v.code}] {v.message}" for v in violations)
        )
