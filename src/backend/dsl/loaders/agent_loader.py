"""YAML-loader декларации :class:`AgentDefinition` (S25-S27, GAP G5).

Назначение:
    Безопасный парсинг YAML-файлов вида ``<name>.agent.yaml`` в
    :class:`AgentDefinition` с Pydantic-валидацией.

Контракт безопасности (V15 R-V15 запрещённые паттерны):
    * Используется только :func:`yaml.safe_load`. Unsafe-теги
      (``!!python/object`` и подобные) отвергаются.
    * Файл читается как UTF-8; кодировка фиксирована.

Public API:
    * :func:`load_agent_yaml` — строка YAML → :class:`AgentDefinition`.
    * :func:`load_agent_yaml_file` — путь к файлу → :class:`AgentDefinition`.
    * :func:`load_agents_from_directory` — рекурсивный обход root каталога,
      возвращает список агентов, отсортированный по имени файла.
    * :class:`AgentDefinitionLoadError` — выбрасывается при невалидном
      YAML/Pydantic-схеме (как :class:`PolicyLoadError`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from src.backend.dsl.models.agent_definition import AgentDefinition

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = (
    "AgentDefinitionLoadError",
    "load_agent_yaml",
    "load_agent_yaml_file",
    "load_agents_from_directory",
)


class AgentDefinitionLoadError(ValueError):
    """Ошибка загрузки YAML-декларации агента.

    Аналог :class:`PolicyLoadError` для AI-агентов. Поднимается при:

    * некорректном синтаксисе YAML;
    * несоответствии Pydantic-схеме :class:`AgentDefinition`;
    * ошибке чтения файла (если использовался ``load_agent_yaml_file``).

    Attributes:
        source: Путь к файлу либо ``"<inline>"`` для inline-YAML.
        reason: Текст исходной ошибки.
    """

    def __init__(self, source: str | Path, reason: str) -> None:
        """Инициализация.

        Args:
            source: Источник YAML (путь к файлу или ``"<inline>"``).
            reason: Описание ошибки из yaml / pydantic.
        """
        super().__init__(f"Не удалось загрузить агента из {source}: {reason}")
        self.source = source
        self.reason = reason


def load_agent_yaml(yaml_text: str) -> AgentDefinition:
    """Парсинг YAML-строки в :class:`AgentDefinition`.

    Args:
        yaml_text: YAML-текст декларации агента.

    Returns:
        Валидированная :class:`AgentDefinition`.

    Raises:
        AgentDefinitionLoadError: При невалидном YAML или несоответствии
            Pydantic-схеме.
    """
    try:
        raw: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise AgentDefinitionLoadError("<inline>", f"YAML parse error: {exc}") from exc
    if raw is None:
        raise AgentDefinitionLoadError("<inline>", "Пустой YAML-документ.")
    if not isinstance(raw, dict):
        raise AgentDefinitionLoadError(
            "<inline>",
            f"Ожидался YAML-mapping на верхнем уровне, получен {type(raw).__name__}.",
        )
    try:
        return AgentDefinition.model_validate(raw)
    except (TypeError, ValueError) as exc:
        raise AgentDefinitionLoadError(
            "<inline>", f"AgentDefinition validation error: {exc}"
        ) from exc


def load_agent_yaml_file(path: str | Path) -> AgentDefinition:
    """Парсинг файла в :class:`AgentDefinition`.

    Args:
        path: Путь к YAML-файлу декларации агента.

    Returns:
        Валидированная :class:`AgentDefinition`.

    Raises:
        AgentDefinitionLoadError: При невалидном YAML, ошибке чтения файла
            или несоответствии Pydantic-схеме.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentDefinitionLoadError(p, f"file read error: {exc}") from exc
    try:
        return load_agent_yaml(text)
    except AgentDefinitionLoadError as exc:
        # Перевыбрасываем, заменяя источник на путь файла для понятного сообщения.
        raise AgentDefinitionLoadError(p, exc.reason) from exc


def load_agents_from_directory(
    root: str | Path, *, suffix: str = ".agent.yaml"
) -> list[AgentDefinition]:
    """Загрузить все декларации агентов из указанного каталога.

    Рекурсивно сканирует ``root`` на файлы с суффиксом ``suffix``.
    Несуществующие каталоги возвращают пустой список без ошибок.

    Args:
        root: Каталог-корень сканирования (``agents/`` или
            ``extensions/<plugin>/agents/``).
        suffix: Расширение/суффикс файлов агентов; default
            ``".agent.yaml"``.

    Returns:
        Список загруженных :class:`AgentDefinition`, отсортированный по
        пути файла (детерминированный порядок).

    Raises:
        AgentDefinitionLoadError: При невалидном файле; ошибка содержит
            конкретный путь.
    """
    base = Path(root)
    if not base.exists() or not base.is_dir():
        return []
    return [load_agent_yaml_file(p) for p in _iter_agent_files(base, suffix)]


def _iter_agent_files(base: Path, suffix: str) -> Iterator[Path]:
    """Итерировать YAML-файлы агентов в детерминированном порядке.

    Args:
        base: Корневой каталог сканирования.
        suffix: Суффикс файлов агентов.

    Yields:
        Пути к файлам в лексикографическом порядке.
    """
    yield from sorted(p for p in base.rglob(f"*{suffix}") if p.is_file())
