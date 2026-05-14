"""OTel Baggage propagation для cross-cutting concerns.

Назначение:
    Централизованное API для установки и чтения обязательных полей
    OpenTelemetry Baggage в каждом span:
      - route_name     — имя DSL-маршрута (или endpoint-а);
      - tenant_id      — идентификатор тенанта;
      - business_op    — бизнес-операция (semantic event name);
      - correlation_id — сквозной идентификатор запроса.

    В strict-режиме (feature_flag.tracing_baggage_strict=True) функция
    ensure_required_baggage() проверяет наличие всех четырёх полей и
    возбуждает MissingBaggageError при отсутствии хотя бы одного.

Использование:
    from src.backend.core.observability.baggage import (
        set_baggage,
        get_baggage,
        with_baggage,
        ensure_required_baggage,
    )

    # Установка baggage в точке входа (middleware/entrypoint)
    set_baggage(
        route_name="credit_check_v2",
        tenant_id="bank_alpha",
        business_op="credit.score.calculate",
        correlation_id="req-abc123",
    )

    # Чтение текущего baggage (downstream service / processor)
    bag = get_baggage()  # -> {"route_name": "...", "tenant_id": "...", ...}

    # Context manager для временного baggage (тесты, subspan)
    async with with_baggage(route_name="health_check"):
        ...

    # Строгая проверка (в strict-режиме)
    ensure_required_baggage()  # raises MissingBaggageError если неполный

Архитектурные ограничения:
    - Lazy-import opentelemetry: не вызывает SDK при старте, если OTel не нужен.
    - feature_flags импортируется только внутри функций (избегаем circular import).
    - Модуль не импортирует ничего из infrastructure/ или services/.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    pass

__all__ = (
    "MissingBaggageError",
    "set_baggage",
    "get_baggage",
    "with_baggage",
    "ensure_required_baggage",
)

# Ключи обязательных baggage-полей (K1 W2)
_KEY_ROUTE_NAME = "route_name"
_KEY_TENANT_ID = "tenant_id"
_KEY_BUSINESS_OP = "business_op"
_KEY_CORRELATION_ID = "correlation_id"

_REQUIRED_KEYS: tuple[str, ...] = (
    _KEY_ROUTE_NAME,
    _KEY_TENANT_ID,
    _KEY_BUSINESS_OP,
    _KEY_CORRELATION_ID,
)


class MissingBaggageError(RuntimeError):
    """Ошибка: обязательные поля OTel baggage не установлены.

    Возбуждается функцией ensure_required_baggage() в strict-режиме
    (feature_flag.tracing_baggage_strict=True), когда хотя бы одно из
    4 обязательных полей (route_name/tenant_id/business_op/correlation_id)
    отсутствует в текущем OTel context.

    Args:
        missing: Список имён отсутствующих ключей.
    """

    def __init__(self, missing: list[str]) -> None:
        """Инициализирует исключение с перечнем пропущенных полей.

        Args:
            missing: Список имён отсутствующих ключей baggage.
        """
        self.missing = missing
        super().__init__(
            f"Обязательные поля OTel baggage отсутствуют: {missing}. "
            "Убедитесь, что middleware propagation установлен в entrypoint."
        )


def set_baggage(
    route_name: str | None = None,
    tenant_id: str | None = None,
    business_op: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Записывает обязательные поля в OpenTelemetry baggage текущего context.

    Функция выполняет lazy-import opentelemetry и последовательно
    устанавливает переданные (не-None) поля через otel_context.attach().
    Поля с None-значением пропускаются (не перезаписывают существующие).

    Args:
        route_name: Имя DSL-маршрута или endpoint-а.
        tenant_id: Идентификатор тенанта (TenantContext.tenant_id).
        business_op: Имя бизнес-операции (semantic event/action name).
        correlation_id: Сквозной correlation-id запроса (X-Correlation-ID).

    Example:
        set_baggage(
            route_name="credit_check_v2",
            tenant_id="bank_alpha",
            business_op="credit.score.calculate",
            correlation_id="req-abc123",
        )
    """
    from opentelemetry import baggage as otel_baggage  # lazy-import
    from opentelemetry import context as otel_context  # lazy-import

    # Собираем только ненулевые поля для установки
    fields: dict[str, str] = {}
    if route_name is not None:
        fields[_KEY_ROUTE_NAME] = route_name
    if tenant_id is not None:
        fields[_KEY_TENANT_ID] = tenant_id
    if business_op is not None:
        fields[_KEY_BUSINESS_OP] = business_op
    if correlation_id is not None:
        fields[_KEY_CORRELATION_ID] = correlation_id

    if not fields:
        return

    # OTel baggage API возвращает новый Context при каждом вызове set_baggage;
    # применяем через attach(), чтобы изменить текущий context в contextvars.
    ctx = otel_context.get_current()
    for key, value in fields.items():
        ctx = otel_baggage.set_baggage(key, value, context=ctx)
    otel_context.attach(ctx)


def get_baggage() -> dict[str, str]:
    """Читает все обязательные baggage-поля из текущего OTel context.

    Возвращает словарь только с теми из 4 обязательных полей, которые
    фактически установлены в текущем context. Отсутствующие поля не
    включаются в результат.

    Returns:
        Словарь с установленными baggage-полями (подмножество из
        route_name, tenant_id, business_op, correlation_id).

    Example:
        bag = get_baggage()
        # -> {"route_name": "credit_check_v2", "tenant_id": "bank_alpha", ...}
    """
    from opentelemetry import baggage as otel_baggage  # lazy-import

    result: dict[str, str] = {}
    for key in _REQUIRED_KEYS:
        value = otel_baggage.get_baggage(key)
        if value is not None:
            result[key] = str(value)
    return result


@asynccontextmanager
async def with_baggage(
    route_name: str | None = None,
    tenant_id: str | None = None,
    business_op: str | None = None,
    correlation_id: str | None = None,
) -> AsyncIterator[None]:
    """Async context manager: устанавливает baggage и восстанавливает предыдущий context.

    При входе в блок сохраняет текущий OTel context, применяет переданные
    поля через set_baggage(), возвращает управление в блок with.
    При выходе восстанавливает предыдущий context через otel_context.detach().

    Подходит для: тестов, subspan-ов, временного переопределения baggage
    в рамках одного request-flow.

    Args:
        route_name: Имя DSL-маршрута или endpoint-а.
        tenant_id: Идентификатор тенанта.
        business_op: Имя бизнес-операции.
        correlation_id: Сквозной correlation-id запроса.

    Yields:
        None — управление передаётся в блок async with.

    Example:
        async with with_baggage(route_name="health_check", tenant_id="sys"):
            bag = get_baggage()
            assert bag["route_name"] == "health_check"
        # после выхода из блока — предыдущий baggage восстановлен
    """
    from opentelemetry import context as otel_context  # lazy-import

    # Сохраняем токен текущего context для последующего detach
    snapshot_ctx = otel_context.get_current()
    token = otel_context.attach(snapshot_ctx)
    try:
        set_baggage(
            route_name=route_name,
            tenant_id=tenant_id,
            business_op=business_op,
            correlation_id=correlation_id,
        )
        yield
    finally:
        otel_context.detach(token)


def _get_feature_flags() -> object:
    """Возвращает singleton feature_flags (lazy-import для избежания circular imports).

    Returns:
        Объект FeatureFlags с текущими значениями флагов.
    """
    from src.backend.core.config.features import feature_flags  # lazy-import

    return feature_flags


def ensure_required_baggage() -> None:
    """Проверяет наличие всех 4 обязательных baggage-полей в текущем context.

    В strict-режиме (feature_flag.tracing_baggage_strict=True) функция
    проверяет route_name, tenant_id, business_op, correlation_id.
    При отсутствии хотя бы одного — возбуждает MissingBaggageError.

    В non-strict режиме (default-OFF) функция завершается без действий,
    что позволяет безопасно добавлять вызовы в entrypoints до активации флага.

    Raises:
        MissingBaggageError: В strict-режиме при отсутствии хотя бы одного
            из обязательных полей baggage.

    Example:
        # В middleware/entrypoint — вызвать после set_baggage()
        ensure_required_baggage()
        # Если strict=True и baggage неполный — получим MissingBaggageError
    """
    flags = _get_feature_flags()
    if not flags.tracing_baggage_strict:  # type: ignore[union-attr]
        # default-OFF: non-strict режим, проверка отключена
        return

    current = get_baggage()
    missing = [key for key in _REQUIRED_KEYS if key not in current]
    if missing:
        raise MissingBaggageError(missing)
