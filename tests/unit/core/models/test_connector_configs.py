"""Tests for ``src.backend.core.models.connector_configs``.

DTO ConnectorConfigEntry (Wave 9.2.3) — запись конфигурации внешнего коннектора.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.backend.core.models.connector_configs import (
    ConnectorConfigEntry,
    _utc_now,
)


class TestUtcNowHelper:
    """_utc_now() — фабрика default для updated_at."""

    def test_returns_aware_datetime(self) -> None:
        result = _utc_now()
        assert isinstance(result, datetime)

    def test_timezone_is_utc(self) -> None:
        result = _utc_now()
        assert result.tzinfo is UTC

    def test_two_calls_close_in_time(self) -> None:
        first = _utc_now()
        second = _utc_now()
        # Допускаем равенство (быстрые CPU), но не отрицательную разницу
        assert (second - first).total_seconds() >= -1


class TestConnectorConfigEntryDefaults:
    """Defaults конструктора Pydantic DTO."""

    def test_minimal_construction(self) -> None:
        entry = ConnectorConfigEntry(name="my_connector")
        assert entry.name == "my_connector"

    def test_default_config_is_empty_dict(self) -> None:
        entry = ConnectorConfigEntry(name="x")
        assert entry.config == {}
        assert isinstance(entry.config, dict)

    def test_default_enabled_is_true(self) -> None:
        entry = ConnectorConfigEntry(name="x")
        assert entry.enabled is True

    def test_default_updated_at_is_recent_utc(self) -> None:
        before = datetime.now(UTC)
        entry = ConnectorConfigEntry(name="x")
        after = datetime.now(UTC)
        assert before <= entry.updated_at <= after

    def test_default_updated_by_is_none(self) -> None:
        entry = ConnectorConfigEntry(name="x")
        assert entry.updated_by is None

    def test_default_version_is_one(self) -> None:
        entry = ConnectorConfigEntry(name="x")
        assert entry.version == 1


class TestConnectorConfigEntryExplicitFields:
    """Явная инициализация всех полей."""

    def test_explicit_config_dict(self) -> None:
        cfg = {"url": "https://example.com", "timeout": 30}
        entry = ConnectorConfigEntry(name="x", config=cfg)
        assert entry.config == cfg

    def test_explicit_enabled_false(self) -> None:
        entry = ConnectorConfigEntry(name="x", enabled=False)
        assert entry.enabled is False

    def test_explicit_updated_at(self) -> None:
        ts = datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC)
        entry = ConnectorConfigEntry(name="x", updated_at=ts)
        assert entry.updated_at == ts

    def test_explicit_updated_by(self) -> None:
        entry = ConnectorConfigEntry(name="x", updated_by="user@bank")
        assert entry.updated_by == "user@bank"

    def test_explicit_version(self) -> None:
        entry = ConnectorConfigEntry(name="x", version=7)
        assert entry.version == 7


class TestConnectorConfigEntryExtra:
    """Поведение extra=ignore — лишние поля тихо отбрасываются."""

    def test_extra_fields_ignored(self) -> None:
        entry = ConnectorConfigEntry(
            name="x",
            unknown_field="foo",
            another=42,
        )
        assert not hasattr(entry, "unknown_field")
        assert not hasattr(entry, "another")

    def test_extra_does_not_raise(self) -> None:
        # extra="ignore" не должен выбрасывать ValidationError
        entry = ConnectorConfigEntry(name="x", bogus=True)
        assert entry.name == "x"


class TestConnectorConfigEntryValidation:
    """Pydantic-валидация типов."""

    def test_missing_required_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConnectorConfigEntry()  # type: ignore[call-arg]

    def test_wrong_type_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConnectorConfigEntry(name=123)  # type: ignore[arg-type]

    def test_wrong_type_enabled_raises(self) -> None:
        # bool("yes") == True в Python → Pydantic coerce-ит в True
        # (Pydantic v2 default strict=False)
        entry = ConnectorConfigEntry(name="x", enabled="yes")  # type: ignore[arg-type]
        assert entry.enabled is True

    def test_wrong_type_version_coerced_to_int(self) -> None:
        # int("1") == 1 → Pydantic coerce-ит в int (default strict=False)
        entry = ConnectorConfigEntry(name="x", version="1")  # type: ignore[arg-type]
        assert entry.version == 1

    def test_truly_invalid_enabled_raises(self) -> None:
        # dict не coerce-ится в bool
        with pytest.raises(ValidationError):
            ConnectorConfigEntry(name="x", enabled={"x": 1})  # type: ignore[arg-type]

    def test_truly_invalid_version_raises(self) -> None:
        # нечисловая строка не coerce-ится в int
        with pytest.raises(ValidationError):
            ConnectorConfigEntry(name="x", version="abc")  # type: ignore[arg-type]


class TestConnectorConfigEntryMutability:
    """Pydantic-модели v2 mutable по умолчанию — можно менять поля после создания."""

    def test_assign_new_value_after_creation(self) -> None:
        entry = ConnectorConfigEntry(name="x")
        entry.enabled = False
        assert entry.enabled is False

    def test_model_copy_preserves_values(self) -> None:
        original = ConnectorConfigEntry(
            name="x",
            config={"k": "v"},
            enabled=False,
            updated_by="admin",
            version=3,
        )
        copy = original.model_copy()
        assert copy.name == "x"
        assert copy.config == {"k": "v"}
        assert copy.enabled is False
        assert copy.updated_by == "admin"
        assert copy.version == 3

    def test_model_copy_update_overrides(self) -> None:
        original = ConnectorConfigEntry(name="x", version=1)
        updated = original.model_copy(update={"version": 2, "updated_by": "alice"})
        assert original.version == 1  # неизменён
        assert updated.version == 2
        assert updated.updated_by == "alice"


class TestConnectorConfigEntryAll:
    """Проверка __all__."""

    def test_all_exports_connector_config_entry(self) -> None:
        from src.backend.core.models import connector_configs

        assert "ConnectorConfigEntry" in connector_configs.__all__