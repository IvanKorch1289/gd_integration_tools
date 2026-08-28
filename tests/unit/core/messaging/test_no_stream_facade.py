"""Regression tests для core.messaging.stream_facade facade removal (Sprint 36 W1, ADR-0282 Phase B).

Покрывает:
1. `core.messaging.stream_facade` import raises ModuleNotFoundError (facade removed)
2. `infrastructure.clients.messaging.stream.get_stream_client` is canonical home
3. Caller migration: `entrypoints/asyncapi/exporter.py:48` теперь import из infrastructure

Per ADR-0282 §3 Phase B (Sprint 36 W1 Item 3): pure lazy facade removal.
Нет architectural debt created (entrypoints→infra уже allowed via ADR-0284).
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_core_messaging_stream_facade_module_does_not_exist() -> None:
    """``core.messaging.stream_facade`` facade fully removed (Sprint 36 W1).

    Pre-fix: 36 LOC фасад с lazy `__getattr__` для 3 symbols:
    `EventBusFacade`, `get_event_bus_facade`, `get_stream_client`.
    Post-fix: callers импортируют из `infrastructure.clients.messaging.stream`
    (canonical home) или `core.messaging.eventbus.facade` (EventBusFacade остаётся
    в core → allowed).

    Asserts:
    - `import src.backend.core.messaging.stream_facade` raises ModuleNotFoundError
    - The module name is not registered в sys.modules
    """
    # Clear any cached import
    sys.modules.pop("src.backend.core.messaging.stream_facade", None)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module("src.backend.core.messaging.stream_facade")

    assert "stream_facade" in str(exc_info.value)


def test_event_bus_facade_remains_in_core() -> None:
    """`core.messaging.eventbus.facade` остаётся (NOT pruned, separate module)."""
    from src.backend.core.messaging.eventbus.facade import (
        EventBusFacade,
        get_event_bus_facade,
    )

    assert EventBusFacade is not None
    assert callable(get_event_bus_facade)


def test_infrastructure_is_canonical_home_for_stream_client() -> None:
    """`infrastructure.clients.messaging.stream.get_stream_client` is canonical."""
    from src.backend.infrastructure.clients.messaging.stream import get_stream_client

    assert callable(get_stream_client)


class TestCallerMigration:
    """Caller migration: 1 prod caller + 0 test mocks (не было mocks)."""

    def test_asyncapi_exporter_inline_imports_infrastructure(self) -> None:
        """`entrypoints/asyncapi/exporter.py:48` (1 prod caller) inline-imports
        `get_stream_client` напрямую из `infrastructure.clients.messaging.stream`.

        Sprint 36 W1: removed core.messaging.stream_facade facade → caller migrated.
        """
        import importlib.resources

        text = (
            importlib.resources.files("src.backend.entrypoints.asyncapi")
            .joinpath("exporter.py")
            .read_text(encoding="utf-8")
        )

        assert (
            "from src.backend.infrastructure.clients.messaging.stream import" in text
        ), (
            "entrypoints/asyncapi/exporter.py должна inline-import из "
            "infrastructure.clients.messaging.stream (Sprint 36 W1 migration)"
        )

        assert "from src.backend.core.messaging.stream_facade" not in text, (
            "entrypoints/asyncapi/exporter.py не должна использовать "
            "core.messaging.stream_facade (Sprint 36 W1: facade removed)"
        )
