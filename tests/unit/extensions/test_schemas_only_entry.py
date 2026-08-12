"""D-A10-100 regression test — SchemasOnlyEntry plugin pattern.

Закрывает D-A10-100 (Cycle 1, Phase 3, Task E-5/A10):
``extensions/{core_admin,dadata,skb}/plugin.toml`` должны иметь
``entry_class = "extensions.<name>.schemas_only:SchemasOnlyEntry"`` —
это schemas-only plugin pattern (плагин содержит ТОЛЬКО Pydantic-схемы,
без runtime entry-point класса).

Done criteria:
- entry_class каждого из 3 плагинов совпадает с ожидаемым dotted-path;
- класс по этому dotted-path реально импортируется;
- ``plugin.toml`` парсится через stdlib ``tomllib`` без ошибок.

Strict-test policy per D-LESSON-11: NO lax assertions.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

EXTENSIONS: tuple[str, ...] = ("core_admin", "dadata", "skb")
REPO_ROOT: Path = Path(__file__).resolve().parents[3]


def _load_plugin_toml(name: str) -> dict:
    """Загрузить extensions/<name>/plugin.toml через stdlib tomllib."""
    path = REPO_ROOT / "extensions" / name / "plugin.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _resolve_entry_class(entry_class: str) -> type:
    """Разрешить ``module:Class`` в реальный класс через importlib.

    ``entry_class`` формат: ``dotted.module.path:ClassName``.
    """
    module_name, _, class_name = entry_class.partition(":")
    assert module_name and class_name, (
        f"entry_class должен быть в формате 'module:Class', got {entry_class!r}"
    )
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    assert cls is not None, f"Класс {class_name!r} не найден в модуле {module_name!r}"
    return cls


class TestSchemasOnlyEntry:
    """D-A10-100: schemas-only plugin entry_class корректны."""

    @pytest.mark.parametrize("name", EXTENSIONS)
    def test_entry_class_matches_schemas_only_pattern(self, name: str) -> None:
        """entry_class каждого из 3 плагинов указывает на SchemasOnlyEntry.

        D-A10-100 fix: schemas-only плагины должны иметь
        ``entry_class = "extensions.<name>.schemas_only:SchemasOnlyEntry"`` —
        это легитимный plugin pattern (плагин содержит только Pydantic-схемы,
        runtime entry-point класс — пустышка).
        """
        manifest = _load_plugin_toml(name)
        entry_class: str = manifest["plugin"]["entry_class"]
        assert entry_class == f"extensions.{name}.schemas_only:SchemasOnlyEntry", (
            f"D-A10-100: {name}/plugin.toml entry_class должен указывать на "
            f"extensions.{name}.schemas_only:SchemasOnlyEntry, got {entry_class!r}"
        )

    @pytest.mark.parametrize("name", EXTENSIONS)
    def test_entry_class_is_importable(self, name: str) -> None:
        """Класс, на который ссылается entry_class, реально импортируется.

        Sanity-check после fix: SchemasOnlyEntry существует в
        ``extensions/<name>/schemas_only.py``.
        """
        manifest = _load_plugin_toml(name)
        entry_class: str = manifest["plugin"]["entry_class"]
        cls = _resolve_entry_class(entry_class)
        assert cls.__name__ == "SchemasOnlyEntry", (
            f"{name}: ожидался SchemasOnlyEntry, got {cls.__name__!r}"
        )

    @pytest.mark.parametrize("name", EXTENSIONS)
    def test_schemas_only_module_exists(self, name: str) -> None:
        """``extensions/<name>/schemas_only.py`` существует на диске."""
        path = REPO_ROOT / "extensions" / name / "schemas_only.py"
        assert path.is_file(), (
            f"D-A10-100: {name}/schemas_only.py отсутствует (schemas-only pattern broken)"
        )

    def test_plugin_toml_parses_for_all_three(self) -> None:
        """Все 3 plugin.toml парсятся tomllib без ошибок.

        Smoke test на валидность TOML-синтаксиса.
        """
        for name in EXTENSIONS:
            manifest = _load_plugin_toml(name)
            assert "plugin" in manifest, (
                f"D-A10-100: {name}/plugin.toml не содержит секцию [plugin]"
            )
            assert "entry_class" in manifest["plugin"], (
                f"D-A10-100: {name}/plugin.toml не содержит entry_class"
            )
            assert "name" in manifest["plugin"], (
                f"D-A10-100: {name}/plugin.toml не содержит name"
            )
