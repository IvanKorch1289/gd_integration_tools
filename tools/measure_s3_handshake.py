#!/usr/bin/env python
"""S3 connection-handshake measurement — evidence for cycle 172 / HIGH-01.

Measures how many ``aiohttp.ClientSession`` objects (i.e. connection pools)
are created for N S3 operations, comparing the two regimes:

* **BEFORE (cycle ≤171)** — a client was constructed and torn down per
  operation. Each client owns its own ``aiohttp.ClientSession`` → its own
  ``TCPConnector`` → its own pool. ``max_pool_connections`` was therefore a
  dead setting and every operation paid a full TCP+TLS handshake.
* **AFTER (cycle 172)** — one long-lived client per storage instance, closed
  explicitly via ``aclose()``.

The measurement runs against ``moto.server.ThreadedMotoServer`` (real S3 wire
protocol). Note that moto answers every request with ``Connection: close``, so
raw TCP-connection counts cannot demonstrate keep-alive on the *server* side —
the client-side pool, which is what the fix controls, is what is measured.

Usage::

    uv run python tools/measure_s3_handshake.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from typing import Any

import aiohttp
from moto.server import ThreadedMotoServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backend.core.config.services.storage import FileStorageSettings  # noqa: E402
from src.backend.infrastructure.storage.s3 import S3ObjectStorage  # noqa: E402

OPERATIONS = 20


def _settings(endpoint: str) -> FileStorageSettings:
    return FileStorageSettings(
        enabled=True,
        provider="minio",
        bucket=f"bench-{uuid.uuid4().hex[:12]}",
        access_key="AKIA-BENCH",
        secret_key="bench-secret",  # noqa: S106 — локальный moto-сервер, без TLS
        endpoint=endpoint,
        interface_endpoint=endpoint,
        use_ssl=False,
        verify=False,  # nosec — local moto server, no TLS
        timeout=5,
        retries=2,
        max_pool_connections=20,
        read_timeout=5,
        key_prefix="bench/",
    )


class _SessionCounter:
    """Считает создания ``aiohttp.ClientSession`` (== создания пулов)."""

    def __init__(self) -> None:
        self.sessions: list[aiohttp.ClientSession] = []
        self._original_init = aiohttp.ClientSession.__init__

    def __enter__(self) -> _SessionCounter:
        original_init = self._original_init
        sessions = self.sessions

        # Именно замыкание, а не bound-method: ``instance.__init__(...)``
        # ищет атрибут в классе, и bound-method подменил бы ``self``.
        def counting_init(
            session: aiohttp.ClientSession, *args: Any, **kwargs: Any
        ) -> None:
            original_init(session, *args, **kwargs)
            sessions.append(session)

        aiohttp.ClientSession.__init__ = counting_init  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: Any) -> None:
        aiohttp.ClientSession.__init__ = self._original_init  # type: ignore[method-assign]

    @property
    def count(self) -> int:
        return len(self.sessions)


async def _run_after(storage: S3ObjectStorage, ops: int) -> tuple[int, float]:
    """Текущая реализация: долгоживущий клиент, N операций."""
    with _SessionCounter() as counter:
        started = time.perf_counter()
        for idx in range(ops):
            await storage.upload(f"bench/{idx}.bin", b"x" * 1024)
        elapsed = time.perf_counter() - started
    return counter.count, elapsed


async def _run_before(storage: S3ObjectStorage, ops: int) -> tuple[int, float]:
    """Эмуляция поведения cycle ≤171: клиент на каждую операцию.

    Точно воспроизводит старый ``_S3Session``::

        self._cm = self._storage._session.client(**kwargs)
        self._s3 = await self._cm.__aenter__()
        ...
        await self._cm.__aexit__(...)

    — клиент входит и выходит на каждую операцию.
    """
    session = storage._session
    kwargs = storage._client_kwargs

    with _SessionCounter() as counter:
        started = time.perf_counter()
        for idx in range(ops):
            cm = session.create_client(**kwargs)
            client = await cm.__aenter__()
            try:
                await client.put_object(
                    Bucket=storage._bucket, Key=f"bench/{idx}.bin", Body=b"x" * 1024
                )
            finally:
                await cm.__aexit__(None, None, None)
        elapsed = time.perf_counter() - started
    return counter.count, elapsed


async def main() -> int:
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"

    try:
        storage = S3ObjectStorage(_settings(endpoint))

        # AFTER: считаем сессии на всём времени жизни клиента — прогрев
        # (bucket creation) + N операций. Ожидание: ровно 1 сессия.
        with _SessionCounter() as after_counter:
            started = time.perf_counter()
            await storage.upload("bench/warmup.bin", b"x")
            for idx in range(OPERATIONS):
                await storage.upload(f"bench/{idx}.bin", b"x" * 1024)
            after_time = time.perf_counter() - started
        after_sessions = after_counter.count

        # BEFORE: клиент на каждую операцию (как было до cycle 172).
        before_sessions, before_time = await _run_before(storage, OPERATIONS)

        await storage.aclose()
    finally:
        server.stop()

    print()
    print("S3 handshake measurement (cycle 172, HIGH-01)")
    print(f"  operations:           {OPERATIONS}")
    print("  max_pool_connections: 20")
    print()
    print(
        f"  BEFORE (client per operation): pools={before_sessions:>3}  "
        f"time={before_time:.3f}s"
    )
    print(
        f"  AFTER  (long-lived client)    : pools={after_sessions:>3}  "
        f"time={after_time:.3f}s"
    )
    print()
    if after_sessions == 1:
        print(
            f"  OK: one connection pool for {OPERATIONS} operations "
            f"(was {before_sessions} before the fix)"
        )
        return 0
    print(f"  FAIL: expected 1 pool, got {after_sessions}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
