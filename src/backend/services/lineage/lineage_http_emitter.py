"""OpenLineage HTTP emitter — production-grade transport для Marquez / OpenLineage server.

Использование::

    from src.backend.services.lineage import (
        OpenLineageHttpEmitter,
        set_lineage_emitter,
    )

    emitter = OpenLineageHttpEmitter(
        url="http://marquez:5000",
        namespace="gd_integration_tools",
    )
    set_lineage_emitter(emitter)  # заменяет InMemoryLineageEmitter

OpenLineage spec: https://openlineage.io/spec/
Endpoint: POST {url}/api/v1/lineage  (Marquez convention)
Payload: RunEvent JSON (см. ``InMemoryLineageEmitter.to_openlineage``).

Resilience:
* Failed POST → queued in-memory (drop-oldest при переполнении).
* Batching: до ``batch_size`` events per POST (default 100).
* Thread-safe (lock для buffer).
* Lazy HTTP: import urllib внутри метода (избегаем import-time side effects).
"""

from __future__ import annotations

import logging
import threading
import urllib.error
import urllib.request
from typing import Any

import orjson

from src.backend.services.lineage.lineage_emitter import (
    InMemoryLineageEmitter,
    _iso_timestamp,
)

__all__ = ("OpenLineageHttpEmitter", "OpenLineageHttpConfig")

_log = logging.getLogger(__name__)


class OpenLineageHttpConfig:
    """Immutable config для HTTP emitter."""

    __slots__ = (
        "url",
        "namespace",
        "timeout_s",
        "batch_size",
        "max_queue",
        "auth_token",
    )

    def __init__(
        self,
        url: str,
        *,
        namespace: str = "gd_integration_tools",
        timeout_s: float = 5.0,
        batch_size: int = 100,
        max_queue: int = 10_000,
        auth_token: str | None = None,
    ) -> None:
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError(f"url должен быть http(s)://, получено {url!r}")
        if batch_size < 1:
            raise ValueError(f"batch_size должен быть >= 1, получено {batch_size}")
        if max_queue < batch_size:
            raise ValueError(
                f"max_queue ({max_queue}) должен быть >= batch_size ({batch_size})"
            )
        self.url = url.rstrip("/")
        self.namespace = namespace
        self.timeout_s = timeout_s
        self.batch_size = batch_size
        self.max_queue = max_queue
        self.auth_token = auth_token


class OpenLineageHttpEmitter(InMemoryLineageEmitter):
    """In-memory + HTTP batch POST к OpenLineage-совместимому серверу.

    Наследует ``InMemoryLineageEmitter`` для ``list_events()`` / ``clear()`` /
    ``to_openlineage()`` (test-friendly). Дополнительно буферизует events и
    batch-POSTит на сервер при достижении ``batch_size``.

    Failed POST:
    * Помечает events как "unsent" (не удаляются из buffer).
    * При следующем ``__call__`` повторяет попытку.
    * Drop-oldest при ``max_queue`` overflow (логируется WARNING).

    Best-effort: emitter не должен ломать caller'а при недоступном сервере.
    """

    def __init__(self, config: OpenLineageHttpConfig) -> None:
        super().__init__()
        self._config = config
        # Unsigned buffer (events waiting to be sent).
        # Каждый event — dict в OpenLineage format (уже serialized).
        self._pending: list[dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        # Stats
        self._sent_count = 0
        self._failed_count = 0
        self._dropped_count = 0

    def __call__(self, event: Any) -> None:
        """Append event в in-memory store + pending buffer.

        Если buffer >= batch_size → flush (sync POST).
        """
        super().__call__(event)
        ol_event = self._to_ol_event(event)
        with self._buffer_lock:
            # Drop oldest if overflow
            if len(self._pending) >= self._config.max_queue:
                drop = len(self._pending) - self._config.max_queue + 1
                del self._pending[:drop]
                self._dropped_count += drop
                _log.warning(
                    "OpenLineage emitter queue overflow: dropped %d oldest events", drop
                )
            self._pending.append(ol_event)
            should_flush = len(self._pending) >= self._config.batch_size

        if should_flush:
            self.flush()

    def flush(self) -> int:
        """Sync flush pending events via batch POST.

        Returns: number of events successfully sent (0 если queue empty / all failed).
        """
        with self._buffer_lock:
            if not self._pending:
                return 0
            batch = self._pending[: self._config.batch_size]
            batch_size = len(batch)

        ok = self._post_batch(batch)
        if ok:
            with self._buffer_lock:
                # Remove successfully sent events
                del self._pending[:batch_size]
                self._sent_count += batch_size
            _log.debug("OpenLineage emitter: sent %d events", batch_size)
            return batch_size
        self._failed_count += batch_size
        _log.warning(
            "OpenLineage emitter: failed to send %d events (will retry)", batch_size
        )
        return 0

    def _post_batch(self, batch: list[dict[str, Any]]) -> bool:
        """POST batch to {url}/api/v1/lineage. Returns True on 2xx."""
        endpoint = f"{self._config.url}/api/v1/lineage"
        try:
            # orjson: ~3x faster than stdlib json.dumps + .encode().
            payload = orjson.dumps(batch, default=str)
        except (TypeError, ValueError) as e:
            _log.error("OpenLineage payload serialization failed: %s", e)
            return False

        # SECURITY: endpoint — config-controlled (lineage.url в Settings),
        # не user input. Production MUST validate https:// schema + restrict egress.
        req = urllib.request.Request(  # noqa: S310
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"gd-integration-tools-lineage/1.0 (ns={self._config.namespace})",
                **(
                    {"Authorization": f"Bearer {self._config.auth_token}"}
                    if self._config.auth_token
                    else {}
                ),
            },
        )
        try:
            # SECURITY: endpoint — config-controlled (lineage.url в Settings),
            # не user input. Production deployments MUST validate endpoint schema
            # (https://) и restrict network egress. См. ADR-NEW-12 (RLS для outbound).
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=self._config.timeout_s
            ) as resp:
                if 200 <= resp.status < 300:
                    return True
                _log.warning(
                    "OpenLineage HTTP %d for %d events", resp.status, len(batch)
                )
                return False
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            OSError,
            TimeoutError,
        ) as e:
            _log.warning("OpenLineage POST failed: %s", e)
            return False

    def _to_ol_event(self, event: Any) -> dict[str, Any]:
        """Convert event to OpenLineage JSON format (single event)."""
        if hasattr(event, "to_dict"):
            data = event.to_dict()
        elif isinstance(event, dict):
            data = dict(event)
        else:
            raise TypeError(
                f"event должен быть LineageEvent или dict, получено {type(event).__name__}"
            )
        node = data.get("node", {})
        return {
            "eventType": "COMPLETE",
            "eventTime": _iso_timestamp(data.get("timestamp", 0.0)),
            "run": {"runId": str(data.get("run_id", ""))},
            "job": {
                "namespace": self._config.namespace,
                "name": node.get("name", "unknown"),
            },
            "inputs": [
                {"namespace": self._config.namespace, "name": pid}
                for pid in data.get("parent_ids", [])
            ],
            "outputs": [
                {
                    "namespace": self._config.namespace,
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
            "payload": data.get("payload", {}),
        }

    @property
    def stats(self) -> dict[str, int]:
        """Snapshot of send/fail/drop counters."""
        with self._buffer_lock:
            return {
                "sent": self._sent_count,
                "failed": self._failed_count,
                "dropped": self._dropped_count,
                "pending": len(self._pending),
            }
