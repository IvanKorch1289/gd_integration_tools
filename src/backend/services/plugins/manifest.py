"""Wave 4.4 — Pydantic-схема `plugin.yaml`.

Манифест объявляет публичную поверхность плагина (actions/repos/processors)
декларативно — это позволяет `PluginLoader` валидировать совместимость
до фактического импорта классов плагина.

Совместимость с Python: поле `python_requires` (PEP 440 spec) проверяется
runtime — плагин со `>=3.15` корректно пропускается на 3.14 с лог-сообщением,
не падая всё приложение.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ("PluginManifest", "PluginManifestError", "load_manifest")


class PluginManifestError(ValueError):
    """Ошибка парсинга `plugin.yaml`."""


class PluginManifest(BaseModel):
    """Декларативный манифест плагина.

    Attributes:
        name: Уникальное имя плагина (snake_case).
        version: Семвер-строка.
        python_requires: Опциональный PEP-440 specifier (`>=3.14,<4`).
        entry_class: Dotted path к `BasePlugin`-наследнику
            (`pkg.module.MyPlugin`). Если задан — `PluginLoader`
            импортирует его явно (запасной путь к entry_points).
        actions: Список action_id, регистрируемых плагином (информативно).
        repositories: Список имён репозиториев, которые плагин расширяет.
        processors: Список имён DSL-процессоров.
        hooks: Список (`repo_name`, `event`) пар.
        config: Произвольные настройки, передаются в `PluginContext.config`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    python_requires: str | None = None
    entry_class: str | None = None
    actions: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    processors: tuple[str, ...] = ()
    hooks: tuple[dict[str, str], ...] = ()
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("python_requires")
    @classmethod
    def _validate_specifier(cls, value: str | None) -> str | None:
        """Проверяет, что `python_requires` — валидный PEP-440 spec."""
        if value is None:
            return None
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"Invalid python_requires: {value!r}") from exc
        return value

    def is_compatible_with_current_python(self) -> bool:
        """Совместим ли плагин с текущим Python."""
        if self.python_requires is None:
            return True
        spec = SpecifierSet(self.python_requires)
        current = ".".join(map(str, sys.version_info[:3]))
        return current in spec


def load_manifest(path: Path | str) -> PluginManifest:
    """Прочитать и распарсить `plugin.yaml` из файла.

    Args:
        path: Путь к манифесту.

    Raises:
        PluginManifestError: Файл не существует или содержит невалидную схему.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise PluginManifestError(f"Manifest not found: {file_path}")
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PluginManifestError(f"Invalid YAML in {file_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PluginManifestError(
            f"Manifest must be a mapping, got {type(raw).__name__}: {file_path}"
        )
    try:
        return PluginManifest.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError → wrap
        raise PluginManifestError(f"Manifest validation failed: {exc}") from exc
