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
import tempfile
import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import (
    processor,  # B-1 fix (cycle 1): registry integration
)

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.workflow.claim_check")

#: Default TTL для redis claim-check entries (1h).
_DEFAULT_TTL_SECONDS: int = 3600


# cycle-5/D-AUDIT-505 — register 4 workflow processors via @processor() decorator
@processor(
    "workflow_claim_check",
    namespace="core",
    capabilities=("workflow.claim_check.store",),
    spec_schema={
        "type": "object",
        "properties": {
            "source_property": {"type": "string"},
            "storage_backend": {"enum": ["s3", "redis", "local"]},
            "bucket": {"type": "string"},
            "max_size_bytes": {"type": "integer", "exclusiveMinimum": 0},
            "to": {"type": "string"},
            "ttl_seconds": {"type": "integer", "exclusiveMinimum": 0},
        },
        "required": ["storage_backend"],
    },
    meta={"tier": 1, "category": "workflow"},
)
class WorkflowClaimCheckProcessor(BaseProcessor):
    """Claim Check pattern: внешнее хранилище для больших payloads.

    Args:
        source_property: Dotted path к полю в exchange (например, "body.payload").
        storage_backend: "s3" | "redis" | "local".
        bucket: Имя bucket (для s3) или префикс (для local/redis).
        max_size_bytes: Порог размера (по умолчанию 1MB; payload меньше — не сохраняем).
        to: Куда записать claim token (по умолчанию "body.payload_claim").
        ttl_seconds: TTL для redis backend (default 3600).
    """

    required_capability: ClassVar[str | None] = "workflow.claim_check.store"
    audit_event: ClassVar[str | None] = "workflow.claim_check.stored"

    SUPPORTED_BACKENDS: ClassVar[tuple[str, ...]] = ("s3", "redis", "local")

    def __init__(
        self,
        *,
        source_property: str = "body.payload",
        storage_backend: str = "local",
        bucket: str = "claim-checks",
        max_size_bytes: int = 1_048_576,
        to: str = "body.payload_claim",
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
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
        self.ttl_seconds = ttl_seconds

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Применяет паттерн Claim Check: выгружает большой payload во внешнее хранилище и заменяет его токеном.

        Args:
            exchange: Текущий обмен с сообщением.
            context: Контекст выполнения процессора.
        """
        if not await self.auth_check(exchange, action="store"):
            return
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

        await self._store(claim_id, serialized)

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

    async def _store(self, claim_id: str, data: bytes) -> None:
        """Dispatch store по backend (local=sync file, redis/s3=async client).

        Args:
            claim_id: Уникальный идентификатор claim'а.
            data: Сериализованный payload (bytes).
        """
        if self.storage_backend == "local":
            await asyncio.to_thread(self._store_local, claim_id, data)
        elif self.storage_backend == "redis":
            await self._store_redis(claim_id, data)
        elif self.storage_backend == "s3":
            await self._store_s3(claim_id, data)

    def _store_local(self, claim_id: str, data: bytes) -> None:
        """Запись payload в локальную файловую систему (для dev)."""
        base = os.environ.get(
            "CLAIM_CHECK_LOCAL_PATH",
            os.path.join(tempfile.gettempdir(), "claim_checks"),
        )
        os.makedirs(base, exist_ok=True)
        full_path = os.path.join(base, claim_id.replace("/", "_"))
        with open(full_path, "wb") as fp:
            fp.write(data)

    async def _store_redis(self, claim_id: str, data: bytes) -> None:
        """Запись payload в Redis с TTL (lazy import — redis опциональная зависимость).

        Args:
            claim_id: Ключ для Redis.
            data: Сериализованный payload (bytes).

        Raises:
            ConnectionError: при недоступности Redis (propagated to caller).
        """
        from src.backend.infrastructure.clients.storage.redis import redis_client

        await redis_client.cache_set(claim_id, data, expire=self.ttl_seconds)

    async def _store_s3(self, claim_id: str, data: bytes) -> None:
        """Запись payload в S3/MinIO (lazy import — aiobotocore опциональная зависимость).

        Args:
            claim_id: Ключ объекта в S3.
            data: Сериализованный payload (bytes).

        Raises:
            Exception: при ошибке S3 (propagated to caller).
        """
        from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client

        s3 = get_s3_client()
        await s3.put_object(
            key=claim_id,
            body=data,
            metadata={"ttl_seconds": str(self.ttl_seconds)},
        )

    async def load_payload(self, claim_id: str) -> bytes | None:
        """Загрузка payload по claim_id из внешнего хранилища.

        Args:
            claim_id: Идентификатор claim'а (из claim_token["claim_id"]).

        Returns:
            Сериализованный payload (bytes) или ``None`` если не найден/expired.
        """
        if self.storage_backend == "local":
            return await asyncio.to_thread(self._load_local, claim_id)
        if self.storage_backend == "redis":
            return await self._load_redis(claim_id)
        if self.storage_backend == "s3":
            return await self._load_s3(claim_id)
        return None

    def _load_local(self, claim_id: str) -> bytes | None:
        """Чтение payload из локальной файловой системы."""
        base = os.environ.get("CLAIM_CHECK_LOCAL_PATH", os.path.join(tempfile.gettempdir(), "claim_checks"))
        full_path = os.path.join(base, claim_id.replace("/", "_"))
        if not os.path.exists(full_path):
            return None
        with open(full_path, "rb") as fp:
            return fp.read()

    async def _load_redis(self, claim_id: str) -> bytes | None:
        """Чтение payload из Redis."""
        from src.backend.infrastructure.clients.storage.redis import redis_client

        return await redis_client.cache_get(claim_id)

    async def _load_s3(self, claim_id: str) -> bytes | None:
        """Чтение payload из S3/MinIO."""
        from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client

        s3 = get_s3_client()
        return await s3.get_object_bytes(claim_id)
