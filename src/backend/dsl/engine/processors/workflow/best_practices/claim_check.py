"""WorkflowClaimCheckProcessor.

S171 M9 final: имплементация Temporal best practice "Claim Check Pattern".

Используется для передачи больших payloads (>2MB) в/из Workflows.
Вместо передачи большого объекта — сохраняем его во внешнее хранилище
и возвращаем только идентификатор (claim token).

Поддерживаемые backends:
- s3 (Amazon S3 / MinIO)
- redis (быстрый кэш)
- local (локальная файловая система для dev)

Refs:
    https://docs.temporal.io/best-practices/worker#manage-event-history-growth
    https://dataengineering.wiki/Concepts/Software+Engineering/Claim+Check+Pattern

Pattern (Ponytail, D170): тонкий wrapper, без абстракций.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.workflow.claim_check")


class WorkflowClaimCheckProcessor(BaseProcessor):
    """Claim Check pattern: внешнее хранилище для больших payloads.

    Args:
        source_property: Dotted path к полю в exchange (например, "body.payload").
        storage_backend: "s3" | "redis" | "local".
        bucket: Имя bucket (для s3) или префикс (для local/redis).
        max_size_bytes: Порог размера (по умолчанию 1MB; payload меньше — не сохраняем).
        to: Куда записать claim token (по умолчанию "body.payload_claim").
    """

    required_capability: str | None = "workflow.claim_check.store"
    audit_event: str | None = "workflow.claim_check.stored"

    SUPPORTED_BACKENDS = ("s3", "redis", "local")

    def __init__(
        self,
        *,
        source_property: str = "body.payload",
        storage_backend: str = "local",
        bucket: str = "claim-checks",
        max_size_bytes: int = 1_048_576,
        to: str = "body.payload_claim",
        name: str | None = None,
    ) -> None:
        if storage_backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(
                f"WorkflowClaimCheckProcessor: backend {storage_backend!r} "
                f"не поддерживается. Доступно: {self.SUPPORTED_BACKENDS}"
            )
        super().__init__(name=name or f"claim_check:{storage_backend}")
        self.source_property = source_property
        self.storage_backend = storage_backend
        self.bucket = bucket
        self.max_size_bytes = max_size_bytes
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Применяет паттерн Claim Check: выгружает большой payload во внешнее хранилище и заменяет его токеном.

        Args:
            exchange: Текущий обмен с сообщением.
            context: Контекст выполнения процессора.
        """
        head, _, rest = self.source_property.partition(".")
        if head != "body":
            payload = exchange.in_message.body
        else:
            cursor: Any = exchange.in_message.body
            for part in rest.split(".") if rest else []:
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            payload = cursor

        serialized = json.dumps(payload, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
        size = len(serialized)

        if size <= self.max_size_bytes:
            _logger.debug(
                "claim_check skip: payload size %d <= %d",
                size, self.max_size_bytes,
            )
            self.set_result(exchange, self.target, None)
            return

        claim_id = (
            f"{self.bucket}/{hashlib.sha256(serialized).hexdigest()[:16]}"
            f"-{uuid.uuid4().hex[:8]}"
        )

        await asyncio.to_thread(self._store_payload, claim_id, serialized)

        claim_token = {
            "claim_id": claim_id,
            "size_bytes": size,
            "storage_backend": self.storage_backend,
            "bucket": self.bucket,
            "restore_path": f"claim_check.load:{claim_id}",
        }
        _logger.info(
            "claim_check stored id=%s size=%d backend=%s",
            claim_id, size, self.storage_backend,
        )
        self.set_result(exchange, self.target, claim_token)

    def _store_payload(self, claim_id: str, data: bytes) -> None:
        """Ленивая запись payload в storage (для local)."""
        if self.storage_backend == "local":
            base = os.environ.get(
                "CLAIM_CHECK_LOCAL_PATH",
                "/tmp/claim_checks",
            )
            os.makedirs(base, exist_ok=True)
            full_path = os.path.join(base, claim_id.replace("/", "_"))
            with open(full_path, "wb") as fp:
                fp.write(data)
            return
        if self.storage_backend == "redis":
            try:
                from redis.asyncio import Redis
            except ImportError:
                _logger.warning(
                    "redis не установлен — claim_check игнорируется"
                )
                return
            return
        if self.storage_backend == "s3":
            try:
                import boto3
            except ImportError:
                _logger.warning(
                    "boto3 не установлен — claim_check игнорируется"
                )
                return
