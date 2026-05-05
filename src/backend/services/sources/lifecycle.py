"""W23 — Lifecycle helper для запуска/остановки всех Source.

Использование в composition root (FastAPI lifespan):

```python
await start_all_sources(
    registry=get_source_registry(),
    invoker=get_invoker_singleton(),
    specs=loaded_source_specs,
    dedupe=MemoryDedupeStore(),
)
# ... shutdown:
await stop_all_sources(get_source_registry())
```

Адаптер ``SourceToInvokerAdapter`` создаётся отдельный на каждый source
и связывается с конкретным action из его :class:`SourceSpec`. Если
``spec.idempotency`` выключен — dedupe не передаётся.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.backend.services.sources.adapter import SourceToInvokerAdapter

if TYPE_CHECKING:
    from src.backend.core.config.source_spec import SourceSpec
    from src.backend.core.interfaces.invoker import Invoker
    from src.backend.services.sources.idempotency import DedupeStore
    from src.backend.services.sources.registry import SourceRegistry

__all__ = ("start_all_sources", "stop_all_sources")

logger = logging.getLogger("services.sources.lifecycle")


async def start_all_sources(
    *,
    registry: SourceRegistry,
    invoker: Invoker,
    specs: list[SourceSpec],
    dedupe: DedupeStore | None = None,
) -> None:
    """Запустить все source по их spec, связав с Invoker через адаптер.

    Args:
        registry: ``SourceRegistry`` (в нём source-инстансы уже
            зарегистрированы через :func:`build_source`).
        invoker: Singleton :class:`Invoker`.
        specs: Список ``SourceSpec`` (для извлечения action/mode/reply_channel).
        dedupe: Опциональный :class:`DedupeStore` для idempotency.
    """
    for spec in specs:
        try:
            source = registry.get(spec.id)
        except KeyError:
            logger.warning(
                "start_all_sources: source %s не в реестре, пропуск", spec.id
            )
            continue
        adapter = SourceToInvokerAdapter(
            invoker,
            spec.action,
            mode=spec.mode,
            dedupe=dedupe if spec.idempotency else None,
            reply_channel=spec.reply_channel,
        )
        try:
            await source.start(adapter.handle)
        except Exception as exc:
            logger.error("Source %s: start failed: %s", spec.id, exc)


async def stop_all_sources(registry: SourceRegistry) -> None:
    """Корректно остановить все зарегистрированные source.

    Параллельно вызывает ``stop()`` для каждого source; ошибки
    индивидуальных источников логируются и не ломают shutdown.
    """
    tasks = [_safe_stop(s.source_id, s.stop()) for s in registry.all()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _safe_stop(source_id: str, coro: object) -> None:
    try:
        await coro  # type: ignore[misc]
    except Exception as exc:
        logger.warning("Source %s: stop failed: %s", source_id, exc)
