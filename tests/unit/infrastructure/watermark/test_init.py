"""Unit-тесты для ленивого импорта ``PostgresWatermarkStore``
через ``src.backend.infrastructure.watermark``.
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


def _inject_fake_postgres_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Подменяет postgres_store модуль, чтобы не тянуть SQLAlchemy/psycopg."""
    fake_mod = types.ModuleType("src.backend.infrastructure.watermark.postgres_store")
    fake_mod.PostgresWatermarkStore = "FakePostgresWatermarkStore"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, fake_mod.__name__, fake_mod)
    return fake_mod


@pytest.fixture
def watermark_mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    _inject_fake_postgres_store(monkeypatch)
    from src.backend.infrastructure import watermark as mod

    return mod


@pytest.mark.unit
class TestWatermarkInit:
    def test_postgres_watermark_store_lazy_import(self, watermark_mod: Any) -> None:
        assert watermark_mod.PostgresWatermarkStore == "FakePostgresWatermarkStore"

    def test_unknown_attribute_raises(self, watermark_mod: Any) -> None:
        with pytest.raises(AttributeError, match="unknown_attr"):
            _ = watermark_mod.unknown_attr
