"""Минимальный тест для fail-loud ``MemcachedBackend.delete_pattern``.

Не требует ``aiomcache`` (не установлен в main venv); проверяет только
семантику pattern-delete, contract-protocol ABC обязательной реализации.

S181 P0-#10: silent warning → ``NotImplementedError`` (fail-loud).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# sys.modules mock для aiomcache — production import в ``__init__`` тогда OK.
aiomcache_mock = MagicMock()
aiomcache_mock.Client = MagicMock()
import sys

sys.modules.setdefault("aiomcache", aiomcache_mock)

from src.backend.infrastructure.cache.backends.memcached import (
    MemcachedBackend,  # noqa: E402
)


def _make_backend() -> MemcachedBackend:
    """Build backend без подключения к Memcached."""
    backend = MemcachedBackend(host="127.0.0.1", port=11211, default_ttl=60)
    backend._client = MagicMock()  # не делаем реальных вызовов
    return backend


@pytest.mark.asyncio
async def test_delete_pattern_raises_not_implemented_error() -> None:
    """S181 P0-#10: ``delete_pattern`` raises вместо silent no-op."""
    backend = _make_backend()
    with pytest.raises(NotImplementedError, match="pattern-delete"):
        await backend.delete_pattern("any:*")


@pytest.mark.asyncio
async def test_delete_pattern_does_not_call_client() -> None:
    """Pattern-delete raise происходит до client.delete — confirm нет side effect."""
    backend = _make_backend()
    try:
        await backend.delete_pattern("any:*")
    except NotImplementedError:
        pass
    backend._client.delete.assert_not_called()
