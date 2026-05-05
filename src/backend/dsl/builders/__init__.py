"""Builders package — тонкая декомпозиция ``RouteBuilder`` на миксины.

Этап B1 (ADR-001): god-object `src/dsl/builder.py` (1313 LOC, ~170 методов)
сохраняется как единственный источник реализации, но публичный API теперь
декомпозирован на 11 «категорий» через миксин-маркеры:

* ``CoreRouteBuilder`` — from_/process/log/build.
* ``EIPMixin`` — Enterprise Integration Patterns.
* ``TransportMixin`` — HTTP/gRPC/WS/SSE/MQTT shortcuts.
* ``StreamingMixin`` — windows/correlation/exactly-once.
* ``AIMixin`` — AI/RAG agents DSL.
* ``RPAMixin`` — browser/forms/self-healing.
* ``BankingMixin`` — банковские helpers.
* ``BankingAIMixin`` — ИИ-обогащение для банковских кейсов.
* ``StorageMixin`` — S3/Redis/DB shortcuts.
* ``SecurityMixin`` — OPA/Casbin/rate-limit.
* ``ObservabilityMixin`` — OTEL/Prometheus hooks.

Каждый миксин в B1 экспортирует подмножество методов `RouteBuilder` как
«view»: это облегчает ревью, автогенерацию документации и статический
анализ. Полный физический разнос методов в отдельные классы
(LOC-бюджет ≤300 на файл) запланирован как **B1 phase-2** в
follow-up-коммите; на текущем этапе мы не двигаем реализацию, чтобы
избежать регрессий и сохранить все существующие контракты.
"""

from __future__ import annotations

from src.backend.dsl.builder import RouteBuilder as _BuilderImpl

# Phase-2 (B1) будет физически разложен на миксины. Сейчас — re-export
# единого класса; публичный импорт `from src.backend.dsl.builders import RouteBuilder`
# уже доступен и даёт одинаковый API.
RouteBuilder = _BuilderImpl

__all__ = (
    "RouteBuilder",
    "CoreMixin",
    "EIPMixin",
    "TransportMixin",
    "StreamingMixin",
    "AIMixin",
    "RPAMixin",
    "BankingMixin",
    "BankingAIMixin",
    "StorageMixin",
    "SecurityMixin",
    "ObservabilityMixin",
)


# ---------------------------------------------------------------------------
# Миксины-маркеры. Каждый — тонкий subclass `_BuilderImpl`, сохраняющий
# поведение. Используются для:
# 1) навигации по публичному API (IDE показывает методы по категориям);
# 2) typing-аннотаций (Protocol-like Group signatures);
# 3) генерации категорийной документации в H1.
# ---------------------------------------------------------------------------


class CoreMixin(_BuilderImpl):
    """Core: `from_`, `.process()`, `.log()`, `.build()`, control-flow."""


class EIPMixin(_BuilderImpl):
    """Enterprise Integration Patterns (Camel/Spring)."""


class TransportMixin(_BuilderImpl):
    """Сетевые транспорты: HTTP/gRPC/WS/SSE/MQTT/Kafka/Rabbit."""


class StreamingMixin(_BuilderImpl):
    """Stream processing: windows, correlation, exactly-once."""


class AIMixin(_BuilderImpl):
    """AI/RAG/agents."""


class RPAMixin(_BuilderImpl):
    """RPA: browser/forms/self-healing locators."""


class BankingMixin(_BuilderImpl):
    """Банковские helpers: ИНН/КПП/SWIFT/IBAN/КБК/business_day/money/fx."""


class BankingAIMixin(_BuilderImpl):
    """ИИ для банковских сценариев: compliance, risk, document-AI."""


class StorageMixin(_BuilderImpl):
    """Storage shortcuts: S3/Redis/Postgres/Qdrant."""


class SecurityMixin(_BuilderImpl):
    """Security: OPA/Casbin/rate-limit/audit."""


class ObservabilityMixin(_BuilderImpl):
    """Observability: OTEL spans, Prometheus, logging."""
