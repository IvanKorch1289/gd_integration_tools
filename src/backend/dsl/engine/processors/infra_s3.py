"""DSL processor ``infra_s3`` (Sprint 170 M2 Phase 2).

S3/MinIO operations через StorageFacade::

    - infra_s3_get:
        key: reports/2026.pdf
        to: body.content

Wave 13 (Q6): процессор больше не обходит фасад. Раньше storage
поднимался напрямую через ``get_object_storage_class()(context)``
(и вообще был нерабочим — модуль ``infrastructure.storage.object_storage``
не существует), из-за чего ``_assert_read`` не вызывался и capability
``storage.read`` не проверялась. Теперь используется общий резолвер
фасада из ``dsl.engine.processors.storage.s3`` — тот же механизм, что
у core-шагов ``to_s3``/``from_s3``/``s3_list``: фасад с capability-check
из ``CapabilityGate`` (svcs_registry) и plugin = route_id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_s3_get",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}, "to": {"type": "string"}},
        "required": ["key"],
    },
    capabilities=("storage.read",),
    meta={"tier": 1, "category": "infra"},
)
class InfraS3GetProcessor(BaseProcessor):
    """Метод InfraS3GetProcessor (см. signature)."""

    def __init__(self, key: str, *, to: str = "body.content") -> None:
        super().__init__(name=f"infra_s3_get:{key}")
        self.key = key
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        # Ленивый импорт общего резолвера фасада: DSL не импортирует
        # services.* на уровне модуля (ADR-0354), а фасад берётся из
        # DI/svcs_registry вместе с capability-check.
        from src.backend.dsl.engine.processors.storage.s3 import _get_storage_facade

        storage = _get_storage_facade(context)
        content = await storage.download(self.key)
        self.set_result(exchange, self.target, content)
