"""BatchProcessor — unified bulk insert/update/delete с chunking.

S39 W3b: ``bulk_insert_mappings`` / ``bulk_update_mappings`` через
``run_sync`` (AsyncSession). Commit per batch → partial-commit.
``IntegrityError`` на duplicate PK → batch пропускается (idempotent).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, ClassVar

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect as sa_inspect

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("BatchProcessor",)

_DEFAULT_PROVIDER: Callable[[], Any] | None = None


def _default_session_provider() -> Callable[[], Any]:
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        from src.backend.infrastructure.database.database import (
            get_external_db_registry,
        )
        def _p() -> Any:
            return get_external_db_registry().get_bundle("default").async_session_maker()
        _DEFAULT_PROVIDER = _p
    return _DEFAULT_PROVIDER


class BatchProcessor(BaseProcessor):
    """Bulk insert/update/delete. Config: mode/model/batch_size/source_field."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        mode: str,
        model: type,
        batch_size: int = 100,
        source_field: str = "rows",
        session_provider: Callable[[], Any] | None = None,
        name: str | None = None,
    ) -> None:
        if mode not in ("insert", "update", "delete"):
            raise ValueError(f"mode должен быть insert/update/delete, получено {mode!r}")
        if batch_size <= 0:
            raise ValueError(f"batch_size должен быть > 0, получено {batch_size}")
        super().__init__(name=name or f"batch_{mode}")
        self._mode, self._model = mode, model
        self._batch_size, self._source_field = batch_size, source_field
        self._session_provider = session_provider or _default_session_provider()

    @handle_processor_error
    async def process(self, exchange: "Exchange", context: "ExecutionContext") -> None:
        rows: Any = exchange.properties.get(self._source_field) or exchange.in_message.body
        key = f"batch_{self._mode}_result"
        if not isinstance(rows, list) or not rows:
            self._set_result(exchange, key, 0, 0, 0, rows)
            return
        batches = [rows[i : i + self._batch_size] for i in range(0, len(rows), self._batch_size)]
        total, committed = await self._run_batches(batches)
        self._set_result(exchange, key, total, committed, len(batches), rows)

    def _set_result(
        self, exchange: "Exchange", key: str,
        processed: int, batches: int, total_batches: int, rows: Any,
    ) -> None:
        sf = self._source_field
        exchange.set_property(key, {
            "mode": self._mode, "processed": processed, "batches": batches,
            "total_batches": total_batches, "affected": processed, "source_field": sf,
        })
        exchange.set_out(body=rows, headers=dict(exchange.in_message.headers))

    async def _run_batches(self, batches: list[list[dict]]) -> tuple[int, int]:
        total = committed = 0
        for batch in batches:
            try:
                async with self._session_provider() as session:
                    if self._mode == "insert":
                        await self._bulk(session, batch, "bulk_insert_mappings")
                    elif self._mode == "update":
                        await self._bulk(session, batch, "bulk_update_mappings")
                    else:
                        await self._do_delete(session, batch)
                    await session.commit()
                total += len(batch)
                committed += 1
            except IntegrityError:
                continue  # Idempotent: duplicate PK — skip batch.
        return total, committed

    async def _bulk(self, session: Any, batch: list[dict], method_name: str) -> None:
        model = self._model

        def _do(sess: Any) -> None:
            getattr(sess, method_name)(model, batch)

        await session.run_sync(_do)

    async def _do_delete(self, session: Any, batch: list[dict]) -> None:
        pk_col = sa_inspect(self._model).primary_key[0]
        ids = [r[pk_col.name] for r in batch if r.get(pk_col.name) is not None]
        if ids:
            await session.execute(delete(self._model).where(pk_col.in_(ids)))

    def to_spec(self) -> dict[str, Any] | None:
        return {"batch": {
            "mode": self._mode,
            "model": getattr(self._model, "__name__", str(self._model)),
            "batch_size": self._batch_size,
            "source_field": self._source_field,
        }}
