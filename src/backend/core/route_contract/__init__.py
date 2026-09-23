"""Route Contract — declarative contract для routes (Wave 1 P0 #25).

Проблема (EP-R1):
    У маршрута нет явного описания:
    - Какие входные данные и схема?
    - Какие side effects (writes to DB, MQ, HTTP)?
    - Какой timeout, retries, idempotency policy?
    - Куда отправлять failed events (DLQ)?
    - Кто owner (team/person)?

    Без этого нельзя:
    - Валидировать route при deploy.
    - Генерировать documentation.
    - Делать impact analysis.
    - Автоматически проверять policy compliance.

Решение:
    ``RouteContract`` — Pydantic model + ``RouteContractRegistry``:

    1. ``RouteContract`` — declarative spec:
       - input_schema, output_schema (JSON Schema).
       - timeout_seconds, retry_policy.
       - idempotency_policy (key_field, ttl_seconds).
       - dlq_policy (topic, max_retries).
       - owner (team).

    2. ``RouteContractRegistry`` — register/lookup contracts.

    3. ``validate_contract(contract)`` — PolicyGate: enforce required fields.

Использование::

    from src.backend.core.route_contract import (
        RouteContract, RetryPolicy, IdempotencyPolicy, DLQPolicy,
        validate_contract,
    )

    contract = RouteContract(
        route_id="order-create",
        input_schema={"type": "object", "required": ["order_id"]},
        timeout_seconds=30.0,
        retry_policy=RetryPolicy(max_attempts=3, backoff="exponential"),
        idempotency_policy=IdempotencyPolicy(key_field="order_id", ttl_seconds=86400),
        dlq_policy=DLQPolicy(topic="events.orders.dlq"),
        owner="team-payments",
    )
    errors = validate_contract(contract)
    if errors:
        raise ValueError(f"Contract violations: {errors}")
"""

from __future__ import annotations

from src.backend.core.route_contract.contract import (
    DLQPolicy,
    IdempotencyPolicy,
    RetryPolicy,
    RouteContract,
    validate_contract,
)
from src.backend.core.route_contract.registry import (
    RouteContractRegistry,
    get_route_contract_registry,
)

__all__ = (
    "DLQPolicy",
    "IdempotencyPolicy",
    "RetryPolicy",
    "RouteContract",
    "RouteContractRegistry",
    "get_route_contract_registry",
    "validate_contract",
)
