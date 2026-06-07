"""Lineage Emitter — in-memory store + OpenLineage-compatible serialization.

v21 §2.1: Data Lineage / Provenance.
Default emitter: append-only in-memory list (per-process). Use
:func:`set_lineage_emitter` в production для S3 / OpenLineage HTTP facade / Kafka.

Usage::

    from src.backend.services.lineage import get_lineage_emitter, LineageEvent

    emitter = get_lineage_emitter()
    emitter(LineageEvent(...))  # append к in-memory store
    events = emitter.list_events()  # retrieve все events (для tests / audit export)
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

__all__ = (
    "InMemoryLineageEmitter",
    "LineageEmitterProtocol",
    "get_lineage_emitter",
    "set_lineage_emitter",
)

_log = logging.getLogger(__name__)


class LineageEmitterProtocol(Protocol):
    """Protocol для lineage emitter (sync — async-wrapping на caller)."""

    def __call__(self, event: Any) -> None: ...
    def list_events(self) -> list[dict[str, Any]]: ...
    def clear(self) -> None: ...
    def to_openlineage(self) -> list[dict[str, Any]]: ...


class InMemoryLineageEmitter:
    """In-memory append-only lineage event store (per-process).

    Thread-safe (lock для atomic append/clear). Production-замены:
    * OpenLineage HTTP facade (Marquez / OpenLineage server)
    * S3 sink (JSON-lines append-only file)
    * Kafka topic (``lineage.events.v1``)
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, event: Any) -> None:
        """Append event к in-memory store."""
        # event может быть LineageEvent или dict (для flexibility)
        if hasattr(event, "to_dict"):
            data = event.to_dict()
        elif isinstance(event, dict):
            data = dict(event)
        else:
            raise TypeError(
                f"event должен быть LineageEvent или dict, получено {type(event).__name__}"
            )
        with self._lock:
            self._events.append(data)
        _log.debug(
            "lineage event %s: run_id=%s type=%s node=%s",
            data.get("event_id", "<no-id>"),
            data.get("run_id"),
            data.get("event_type"),
            data.get("node", {}).get("id"),
        )

    def list_events(self) -> list[dict[str, Any]]:
        """Возвращает copy всех stored events."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Очищает store (для tests)."""
        with self._lock:
            self._events.clear()

    def to_openlineage(self) -> list[dict[str, Any]]:
        """Convert events в OpenLineage-compatible JSON.

        OpenLineage spec: https://openlineage.io/spec/
        Каждый event — RunEvent с inputs/outputs/job facets.
        """
        out: list[dict[str, Any]] = []
        for ev in self.list_events():
            node = ev.get("node", {})
            ol_event = {
                "eventType": "COMPLETE",
                "eventTime": _iso_timestamp(ev.get("timestamp", 0.0)),
                "run": {"runId": str(ev.get("run_id", ""))},
                "job": {
                    "namespace": node.get("type", "dataset"),
                    "name": node.get("name", "unknown"),
                },
                "inputs": [
                    {"namespace": "dataset", "name": pid}
                    for pid in ev.get("parent_ids", [])
                ],
                "outputs": [
                    {
                        "namespace": node.get("type", "dataset"),
                        "name": node.get("id", "unknown"),
                        "facets": {
                            "documentation": {
                                "description": ", ".join(
                                    f"{k}={v!r}"
                                    for k, v in (node.get("attributes") or {}).items()
                                )
                            }
                        },
                    }
                ],
                "payload": ev.get("payload", {}),
            }
            out.append(ol_event)
        return out


def _iso_timestamp(unix_ts: float) -> str:
    """Unix timestamp → ISO 8601 string (OpenLineage format)."""
    from datetime import datetime, timezone

    return (
        datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ── Module-level singleton (DI-friendly) ──────────────────────────────
_emitter: InMemoryLineageEmitter | None = None
_emitter_lock = threading.Lock()


def get_lineage_emitter() -> InMemoryLineageEmitter:
    """Return module-level singleton (DI-friendly)."""
    global _emitter
    if _emitter is None:
        with _emitter_lock:
            if _emitter is None:
                _emitter = InMemoryLineageEmitter()
    return _emitter


def set_lineage_emitter(emitter: InMemoryLineageEmitter) -> None:
    """Replace module-level singleton (для tests / production swap)."""
    global _emitter
    with _emitter_lock:
        _emitter = emitter


def reset_lineage_emitter() -> InMemoryLineageEmitter:
    """Clear store + return fresh emitter (только для tests).

    Также очищает старый emitter instance (если он был singleton) — иначе
    old instance в references держит накопленные events.
    """
    global _emitter
    with _emitter_lock:
        if _emitter is not None:
            _emitter.clear()
        _emitter = InMemoryLineageEmitter()
    return _emitter


# Type alias for callable usage
LineageEmitterCallable = Callable[[Any], None]
