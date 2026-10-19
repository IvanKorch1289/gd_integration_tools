"""Tests for ``src.backend.dsl.versioning.migrations_v1_to_v2``.

W25.3: identity-миграция v1 → v2 (apiVersion + _migrated_from history).
"""

from __future__ import annotations

from src.backend.dsl.versioning.migrations_v1_to_v2 import V1ToV2Migration


class TestVersionMetadata:
    """Class-level from_version/to_version."""

    def test_from_version_is_v1(self) -> None:
        assert V1ToV2Migration.from_version == "v1"

    def test_to_version_is_v2(self) -> None:
        assert V1ToV2Migration.to_version == "v2"


class TestMigrateEmptySpec:
    """Migrate пустой/минимальный spec."""

    def test_empty_dict(self) -> None:
        result = V1ToV2Migration().migrate({})
        # _migrated_from добавлен, история содержит 'v1'
        assert result["_migrated_from"] == ["v1"]

    def test_returns_dict_copy(self) -> None:
        original = {}
        result = V1ToV2Migration().migrate(original)
        assert result is not original

    def test_does_not_modify_original(self) -> None:
        original = {"foo": "bar"}
        V1ToV2Migration().migrate(original)
        assert original == {"foo": "bar"}


class TestMigrateExistingFields:
    """Migrate spec с существующими полями."""

    def test_preserves_existing_keys(self) -> None:
        spec = {"name": "test", "kind": "route"}
        result = V1ToV2Migration().migrate(spec)
        assert result["name"] == "test"
        assert result["kind"] == "route"

    def test_adds_migrated_from_to_spec_without_history(self) -> None:
        spec = {"name": "test"}
        result = V1ToV2Migration().migrate(spec)
        assert result["_migrated_from"] == ["v1"]


class TestMigrateExistingHistory:
    """Migrate spec с уже существующей историей миграций."""

    def test_appends_to_existing_history(self) -> None:
        spec = {"_migrated_from": ["v0", "v0.5"]}
        result = V1ToV2Migration().migrate(spec)
        assert result["_migrated_from"] == ["v0", "v0.5", "v1"]


class TestMigrateDeduplicatesV1:
    """Если v1 уже последний в истории — не дублируется."""

    def test_does_not_duplicate_v1_at_end(self) -> None:
        # Если history[-1] == "v1" — не добавляем ещё раз
        spec = {"_migrated_from": ["v0", "v1"]}
        result = V1ToV2Migration().migrate(spec)
        # Не должно быть ['v0', 'v1', 'v1']
        assert result["_migrated_from"] == ["v0", "v1"]

    def test_appends_v1_if_history_ends_with_different_version(self) -> None:
        # history[-1] != "v1" → добавляем
        spec = {"_migrated_from": ["v0", "v0.5"]}
        result = V1ToV2Migration().migrate(spec)
        assert result["_migrated_from"] == ["v0", "v0.5", "v1"]

    def test_appends_v1_if_history_ends_with_v0(self) -> None:
        spec = {"_migrated_from": ["v0"]}
        result = V1ToV2Migration().migrate(spec)
        assert result["_migrated_from"] == ["v0", "v1"]


class TestEmptyHistoryDeduplication:
    """Пустая история — v1 добавляется."""

    def test_empty_history_gets_v1(self) -> None:
        spec = {"_migrated_from": []}
        result = V1ToV2Migration().migrate(spec)
        # history[-1] — IndexError на пустом list → falls into "not history or ..." → добавляем
        assert result["_migrated_from"] == ["v1"]


class TestMigrateReturnsNewDict:
    """migrate() возвращает новый dict."""

    def test_returns_new_dict(self) -> None:
        spec = {"x": 1}
        result = V1ToV2Migration().migrate(spec)
        assert result is not spec
        assert isinstance(result, dict)

    def test_payload_dict_copied(self) -> None:
        spec = {"x": 1}
        result = V1ToV2Migration().migrate(spec)
        result["new_key"] = "new_value"
        assert "new_key" not in spec


class TestMultipleMigrations:
    """Несколько миграций подряд."""

    def test_consecutive_migrations_accumulate_history(self) -> None:
        spec = {}
        r1 = V1ToV2Migration().migrate(spec)
        # r1: _migrated_from = ['v1']
        # Если v1 уже последний — dedup
        r2 = V1ToV2Migration().migrate(r1)
        # v1 уже последний → не добавляется
        assert r2["_migrated_from"] == ["v1"]


class TestTypeAnnotations:
    """Type hints корректные."""

    def test_migrate_signature(self) -> None:
        import inspect

        sig = inspect.signature(V1ToV2Migration.migrate)
        params = sig.parameters
        assert "spec" in params
        ann = str(sig.return_annotation)
        assert "dict" in ann.lower()


class TestInstanceCreation:
    """Class can be instantiated."""

    def test_no_args_construction(self) -> None:
        m = V1ToV2Migration()
        assert m is not None
        assert m.from_version == "v1"
        assert m.to_version == "v2"


class TestDifferenceFromV0ToV1:
    """Проверка что v1→v2 отличается от v0→v1 в логике dedup."""

    def test_v0_to_v1_always_appends(self) -> None:
        """V0ToV1: всегда append 'v0', без dedup."""
        from src.backend.dsl.versioning.migrations_v0_to_v1 import V0ToV1Migration

        spec = {"_migrated_from": ["v0"]}
        result = V0ToV1Migration().migrate(spec)
        # Дубликат v0
        assert result["_migrated_from"] == ["v0", "v0"]

    def test_v1_to_v2_dedups_last_v1(self) -> None:
        """V1ToV2: dedup если v1 последний."""
        spec = {"_migrated_from": ["v0", "v1"]}
        result = V1ToV2Migration().migrate(spec)
        # Не дублирует
        assert result["_migrated_from"] == ["v0", "v1"]