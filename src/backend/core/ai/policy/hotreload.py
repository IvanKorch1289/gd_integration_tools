"""S77 W1 — Policy hot-reload через watchfiles (P0-C closure, ADR-0067).

До S77: :meth:`PolicyResolver.reload` существовал, но caller
(administration endpoint / Wave B watcher) должен был вручную
вызвать его. S77 W1: добавляет :func:`watch_policy_files` async
generator, который использует :func:`watchfiles.awatch` для
real-time file watching и автоматически call'ит ``resolver.reload()``.

**Design**:
* Async generator yields :class:`PolicyReloadEvent` для каждого
  change (added/modified/deleted).
* Caller обрабатывает events: invalidates cache, re-loads policies.
* Graceful shutdown: stop_event / cancellation.
* Optional callback: ``on_reload(policy_name)`` для logging.

**Use case** (FINAL_REPORT_V2 P0-C):
```python
resolver = PolicyResolver(roots=[Path("ai_policies")])
async for event in watch_policy_files(resolver, paths=[Path("ai_policies")]):
    _logger.info("Policy reload: %s (action=%s)", event.path, event.action)
```

**Limitations**:
* Только file-level events (не детальный diff — caller не знает
  какие поля changed).
* Polling-based fallback через ``force_polling=True`` для NFS/некоторых
  filesystems (debounce 1600ms).
* No transactional reload — partial file write может привести к
  inconsistent state (YAML parse error → PolicyLoadError).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.resolver import PolicyResolver

_logger = get_logger("core.ai.policy.hotreload")

__all__ = ("PolicyReloadAction", "PolicyReloadEvent", "watch_policy_files")


class PolicyReloadAction(str, Enum):
    """S77 W1 — тип change event для policy files."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class PolicyReloadEvent:
    """S77 W1 — file change event для policy hot-reload.

    Attributes:
        path: абсолютный path к изменившемуся файлу.
        action: тип change (ADDED / MODIFIED / DELETED).
    """

    path: Path
    action: PolicyReloadAction


async def watch_policy_files(
    resolver: "PolicyResolver",
    *,
    paths: list[Path] | None = None,
    stop_event: asyncio.Event | None = None,
    on_reload: Callable[[PolicyReloadEvent], None] | None = None,
) -> AsyncIterator[PolicyReloadEvent]:
    """Async generator, watch'ит policy files и reload'ит resolver.

    Использует :func:`watchfiles.awatch` для real-time FS events.
    На каждое event: вызывает ``resolver.reload()`` (clears cache +
    marks policies для re-load) и yields :class:`PolicyReloadEvent`
    для caller'а (logging / metrics).

    Args:
        resolver: :class:`PolicyResolver` для reload при change.
        paths: Список директорий для watching. Default:
            ``resolver._roots`` (private API — prefer explicit).
        stop_event: asyncio.Event для graceful shutdown. Stop event
            set → generator exits gracefully.
        on_reload: Optional callback ``callable(event: PolicyReloadEvent)``
            вызывается ПОСЛЕ resolver.reload() и ПЕРЕД yield'ом event.
            Use case: metrics increment, audit log.

    Yields:
        :class:`PolicyReloadEvent` для каждого detected change.

    Raises:
        ImportError: watchfiles не установлен.
        OSError: invalid path / permission denied.

    Example:
        >>> resolver = PolicyResolver(roots=[Path("ai_policies")])
        >>> async for event in watch_policy_files(resolver):
        ...     _logger.info("Policy %s: %s", event.action, event.path)
    """
    try:
        from watchfiles import Change, awatch  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "watchfiles required для hot-reload. "
            "Install: uv add watchfiles (уже в dev-group)."
        ) from exc

    if paths is None:
        # Use resolver's internal roots (private API, но acceptable для default)
        paths = resolver._roots  # type: ignore[attr-defined]
    if not paths:
        _logger.warning("watch_policy_files called with empty paths")
        return

    # Filter watch_filter: ignore __pycache__ etc (default watchfiles filter).
    def _policy_filter(change: Change, path: str) -> bool:
        # Only .policy.yaml files
        return path.endswith(".policy.yaml")

    _logger.info(
        "Starting policy hot-reload watcher (paths=%s, debounce=1600ms)",
        [str(p) for p in paths],
    )

    async for changes in awatch(
        *paths,
        watch_filter=_policy_filter,
        debounce=1600,  # 1.6s — reduces flapping на rapid saves
    ):
        if stop_event is not None and stop_event.is_set():
            _logger.info("Policy hot-reload: stop_event set, exiting")
            return
        for change_type, path_str in changes:
            path = Path(path_str)
            # Map watchfiles Change enum to PolicyReloadAction
            if change_type == Change.added:
                action = PolicyReloadAction.ADDED
            elif change_type == Change.modified:
                action = PolicyReloadAction.MODIFIED
            elif change_type == Change.deleted:
                action = PolicyReloadAction.DELETED
            else:
                _logger.debug("Skipping unknown change: %s", change_type)
                continue

            # S77 W1: reload resolver (clears cache + re-loads on next resolve)
            try:
                resolver.reload()
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "resolver.reload() failed after %s %s: %s", action, path, exc
                )
                # Continue (не raise — другие файлы могут быть valid)

            event = PolicyReloadEvent(path=path, action=action)
            if on_reload is not None:
                try:
                    on_reload(event)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("on_reload callback failed: %s", exc)

            _logger.info("Policy %s: %s (resolver reloaded)", action.value, path)
            yield event
