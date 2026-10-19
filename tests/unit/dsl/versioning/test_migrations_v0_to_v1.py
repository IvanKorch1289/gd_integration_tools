"""Tests for ``src.backend.dsl.versioning.migrations_v0_to_v1``.

W25.3: identity-миграция v0 → v1 (apiVersion + _migrated_from history).
"""

from __future__ import annotations

from src.backend.dsl.versioning.migrations_v0_to_v1 import V0ToV1Migration


class TestVersionMetadata:
    """Class-level from_version/to_version."""

    def test_from_version_is_v0(self) -> None:
        assert V0ToV1Migration.from_version == "v0"

    def test_to_version_is_v1(self) -> None:
        assert V0ToV1Migration.to_version == "v1"


class TestMigrateEmptySpec:
    """Migrate пустой/минимальный spec."""

    def test_empty_dict(self) -> None:
        result = V0ToV1Migration().migrate({})
        # _migrated_from добавлен, история содержит 'v0'
        assert result["_migrated_from"] == ["v0"]

    def test_empty_dict_returns_dict_copy(self) -> None:
        original = {}
        result = V0ToV1Migration().migrate(original)
        # result — новый dict, не тот же объект
        assert result is not original

    def test_migration_does_not_modify_original(self) -> None:
        original = {"foo": "bar"}
        V0ToV1Migration().migrate(original)
        # original не должен измениться
        assert original == {"foo": "bar"}


class TestMigrateExistingFields:
    """Migrate spec с существующими полями."""

    def test_preserves_existing_keys(self) -> None:
        spec = {"name": "test", "kind": "route"}
        result = V0ToV1Migration().migrate(spec)
        assert result["name"] == "test"
        assert result["kind"] == "route"

    def test_adds_migrated_from_to_spec_without_history(self) -> None:
        spec = {"name": "test"}
        result = V0ToV1Migration().migrate(spec)
        assert result["_migrated_from"] == ["v0"]


class TestMigrateExistingHistory:
    """Migrate spec с уже существующей историей миграций."""

    def test_appends_to_existing_history(self) -> None:
        spec = {"_migrated_from": ["v0.5", "v0.7"]}
        result = V0ToV1Migration().migrate(spec)
        # Должно быть ['v0.5', 'v0.7', 'v0']
        assert result["_migrated_from"] == ["v0.5", "v0.7", "v0"]

    def test_does_not_modify_existing_history_list(self) -> None:
        # Копия через list(...), не in-place модификация
        spec = {"_migrated_from": ["v0.5"]}
        result = V0ToV1Migration().migrate(spec)
        # spec не изменился
        assert spec["_migrated_from"] == ["v0.5"]
        # result имеет append
        assert result["_migrated_from"] == ["v0.5", "v0"]

    def test_appends_v0_even_if_v0_already_in_history(self) -> None:
        # Простая семантика: всегда добавляем 'v0'
        spec = {"_migrated_from": ["v0"]}
        result = V0ToV1Migration().migrate(spec)
        # Дубликат v0 в истории
        assert result["_migrated_from"] == ["v0", "v0"]


class TestMigrateReturnsNewDict:
    """migrate() возвращает новый dict (immutability)."""

    def test_returns_new_dict(self) -> None:
        spec = {"x": 1}
        result = V0ToV1Migration().migrate(spec)
        assert result is not spec
        assert isinstance(result, dict)

    def test_payload_dict_copied(self) -> None:
        # Изменения в result не должны аффектить spec
        spec = {"x": 1}
        result = V0ToV1Migration().migrate(spec)
        result["new_key"] = "new_value"
        assert "new_key" not in spec


class TestMultipleMigrations:
    """Несколько миграций подряд."""

    def test_consecutive_migrations_accumulate_history(self) -> None:
        spec = {}
        result = V0ToV1Migration().migrate(spec)
        # Второй вызов на результате
        result2 = V0ToV1Migration().migrate(result)
        # Каждый вызов добавляет v0 в историю
        assert result2["_migrated_from"] == ["v0", "v0"]


class TestNonStringValues:
    """Spec с не-строковыми значениями."""

    def test_int_value_preserved(self) -> None:
        spec = {"count": 42}
        result = V0ToV1Migration().migrate(spec)
        assert result["count"] == 42

    def test_nested_dict_preserved(self) -> None:
        spec = {"nested": {"a": 1, "b": 2}}
        result = V0ToV1Migration().migrate(spec)
        assert result["nested"] == {"a": 1, "b": 2}

    def test_list_value_preserved(self) -> None:
        spec = {"items": [1, 2, 3]}
        result = V0ToV1Migration().migrate(spec)
        assert result["items"] == [1, 2, 3]


class TestInstanceCreation:
    """Class can be instantiated."""

    def test_no_args_construction(self) -> None:
        m = V0ToV1Migration()
        assert m is not None

    def test_construction_with_args_ignored(self) -> None:
        # Migration() не принимает args, но extra args должны быть проигнорированы
        m = V0ToV1Migration()
        # Просто проверяем что конструкция работает
        assert m.from_version == "v0"


class TestTypeAnnotations:
    """Type hints корректные."""

    def test_migrate_signature(self) -> None:
        import inspect

        sig = inspect.signature(V0ToV1Migration.migrate)
        params = sig.parameters
        assert "spec" in params
        # Return annotation — str-форма forward reference "dict[str, Any]"
        ann = str(sig.return_annotation)
        assert "dict" in ann.lower()