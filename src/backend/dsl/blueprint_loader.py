"""Loader для R2 blueprint YAML-файлов (Wave [wave:s5/k3-w6-blueprints]).

Сканирует ``src/backend/dsl/blueprints/*.yaml``, парсит manifest каждого
blueprint и возвращает list[BlueprintSpec] для регистрации в
:class:`ServiceDSLRegistry` или :class:`ProcessorRegistry`.

Контракт YAML файла blueprint::

    blueprint: <name>
    version: <semver>
    description: <text>
    tags: [...]
    params:
      - name: <param>
        type: string|integer|number|boolean
        required: true|false
        description: <text>
    from: { ... }       # source-spec
    steps: [...]        # pipeline steps
    to: { ... }         # destination-spec

Все параметры в pipeline используются через ``${blueprint.<name>}`` placeholders.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = (
    "DEFAULT_BLUEPRINTS_DIR",
    "BlueprintParam",
    "BlueprintSpec",
    "discover_blueprints",
    "load_blueprint",
)


_logger = get_logger("dsl.blueprints.loader")


DEFAULT_BLUEPRINTS_DIR = Path(__file__).parent / "blueprints"


@dataclass(frozen=True, slots=True)
class BlueprintParam:
    """Параметр blueprint (использовался в YAML через ``${blueprint.<name>}``)."""

    name: str
    type: str = "string"
    required: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BlueprintParam:
        return cls(
            name=str(d.get("name", "")),
            type=str(d.get("type", "string")),
            required=bool(d.get("required", False)),
            description=str(d.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class BlueprintSpec:
    """Спецификация blueprint (parsed from YAML).

    Args:
        name: Имя blueprint (значение поля ``blueprint`` в YAML).
        version: Semver-версия.
        description: Описание сценария.
        tags: Теги для категоризации.
        params: Список параметров (BlueprintParam).
        source: dict ``from`` из YAML.
        steps: list ``steps[]`` из YAML.
        destination: dict ``to`` из YAML.
        path: Путь до исходного YAML-файла.
    """

    name: str
    version: str
    description: str
    tags: tuple[str, ...]
    params: tuple[BlueprintParam, ...]
    source: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    destination: dict[str, Any]
    path: Path = field(default_factory=Path)

    def required_param_names(self) -> tuple[str, ...]:
        """Возвращает имена required-параметров (для валидации запроса)."""
        return tuple(p.name for p in self.params if p.required)


def load_blueprint(path: Path) -> BlueprintSpec:
    """Загрузить один blueprint YAML-файл.

    Args:
        path: Путь до .yaml файла.

    Returns:
        ``BlueprintSpec``.

    Raises:
        ValueError: Manifest невалиден (нет ``blueprint``/``steps``).
    """
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Blueprint {path}: top-level must be dict")

    name = raw.get("blueprint")
    if not name or not isinstance(name, str):
        raise ValueError(f"Blueprint {path}: missing required 'blueprint' field")

    steps = raw.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError(f"Blueprint {path}: 'steps' must be list")

    params_raw = raw.get("params") or []
    params = tuple(
        BlueprintParam.from_dict(p) for p in params_raw if isinstance(p, dict)
    )

    return BlueprintSpec(
        name=name,
        version=str(raw.get("version", "1.0.0")),
        description=str(raw.get("description", "")),
        tags=tuple(raw.get("tags") or ()),
        params=params,
        source=dict(raw.get("from") or {}),
        steps=tuple(steps),
        destination=dict(raw.get("to") or {}),
        path=path,
    )


def discover_blueprints(
    directory: Path | None = None, *, glob: str = "*.yaml"
) -> list[BlueprintSpec]:
    """Найти все *.yaml blueprint в каталоге.

    Args:
        directory: Каталог для скана (default — каталог с этим модулем).
        glob: Паттерн для поиска.

    Returns:
        Список ``BlueprintSpec``, отсортированный по имени.
    """
    directory = directory or DEFAULT_BLUEPRINTS_DIR
    if not directory.is_dir():
        _logger.warning("blueprints discover: directory %s not found", directory)
        return []
    specs: list[BlueprintSpec] = []
    for yaml_path in sorted(directory.glob(glob)):
        try:
            specs.append(load_blueprint(yaml_path))
        except (ValueError, yaml.YAMLError) as exc:
            _logger.error("Failed to load blueprint %s: %s", yaml_path, exc)
    return specs
