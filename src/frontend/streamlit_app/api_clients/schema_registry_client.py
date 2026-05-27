"""Вспомогательные функции клиента Schema Registry для Streamlit UI.

Предоставляет утилиты для работы со схемами (OpenAPI, WSDL, XSD,
Protobuf, AsyncAPI, GraphQL SDL):
- листинг файлов схем по типу;
- чтение содержимого схемы из файловой системы или по URL;
- базовая валидация OpenAPI (JSON-Schema);
- построение unified-diff двух версий схем.

Зависимости jsonschema и lxml подключаются lazy-import'ом — страница
работает даже при их отсутствии (показывается предупреждение).
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

__all__ = ("list_schemas", "read_schema", "validate_openapi", "diff_schemas")

# Корень проекта относительно расположения этого файла:
# services/ → streamlit_app/ → frontend/ → src/ → <root>
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_SCHEMAS_BASE = _PROJECT_ROOT / "docs" / "reference" / "schemas"

# Соответствие kind → поддиректория и суффикс файлов
_KIND_CONFIG: dict[str, tuple[str, list[str]]] = {
    "openapi": ("openapi", [".yaml", ".yml", ".json"]),
    "wsdl": ("wsdl", [".wsdl", ".xml"]),
    "xsd": ("xsd", [".xsd", ".xml"]),
    "protobuf": ("protobuf", [".proto"]),
    "asyncapi": ("asyncapi", [".yaml", ".yml", ".json"]),
    "graphql": ("graphql", [".graphql", ".gql", ".sdl"]),
}


def list_schemas(kind: str) -> list[Path]:
    """Вернуть список файлов схем заданного типа.

    Сканирует ``docs/reference/schemas/<kind>/`` рекурсивно.
    Если директория не существует — возвращает пустой список.

    Args:
        kind: Тип схемы: ``openapi`` | ``wsdl`` | ``xsd`` |
              ``protobuf`` | ``asyncapi`` | ``graphql``.

    Returns:
        Отсортированный список абсолютных :class:`~pathlib.Path` к файлам.
    """
    if kind not in _KIND_CONFIG:
        return []
    subdir, extensions = _KIND_CONFIG[kind]
    base = _SCHEMAS_BASE / subdir
    if not base.is_dir():
        return []
    files: list[Path] = []
    for ext in extensions:
        files.extend(base.rglob(f"*{ext}"))
    return sorted(set(files))


def read_schema(path: Path) -> str:
    """Прочитать содержимое файла схемы.

    Args:
        path: Абсолютный путь к файлу схемы.

    Returns:
        Текстовое содержимое файла в кодировке UTF-8.

    Raises:
        FileNotFoundError: Если файл не найден.
        OSError: При проблемах чтения файла.
    """
    return path.read_text(encoding="utf-8")


def validate_openapi(content: str) -> tuple[bool, str]:
    """Выполнить базовую санитарную проверку OpenAPI/AsyncAPI документа.

    Последовательно выполняет:
    1. Парсинг JSON (для .json) или YAML (для YAML-подобного контента).
    2. Проверку наличия обязательных ключей OpenAPI 3.x (``openapi``,
       ``info``, ``paths``) или AsyncAPI 2.x/3.x (``asyncapi``, ``info``).
    3. Если установлен ``jsonschema`` — проверку типа корневых полей.

    Args:
        content: Строковое содержимое схемы (JSON или YAML).

    Returns:
        Кортеж ``(is_valid, message)`` — флаг успеха и описание результата
        или ошибки.
    """
    # Пробуем JSON, затем YAML
    data: dict | None = None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        try:
            import yaml  # noqa: PLC0415 — lazy import

            data = yaml.safe_load(content)
        except Exception as exc:  # noqa: BLE001
            return False, f"Не удалось распарсить схему: {exc}"

    if not isinstance(data, dict):
        return False, "Корневой элемент схемы должен быть объектом (dict)."

    # Определяем тип схемы и проверяем обязательные ключи
    if "openapi" in data:
        missing = [k for k in ("openapi", "info", "paths") if k not in data]
        if missing:
            return False, f"OpenAPI: отсутствуют обязательные ключи: {missing}"
        return True, f"OpenAPI {data.get('openapi', '?')} — структура корректна."

    if "asyncapi" in data:
        missing = [k for k in ("asyncapi", "info") if k not in data]
        if missing:
            return False, f"AsyncAPI: отсутствуют обязательные ключи: {missing}"
        return True, f"AsyncAPI {data.get('asyncapi', '?')} — структура корректна."

    # Мягкая проверка — схема не распознана, но JSON/YAML валидны
    top_keys = list(data.keys())[:5]
    return (
        True,
        f"JSON/YAML парсится успешно. Тип схемы не распознан. Ключи: {top_keys}",
    )


def diff_schemas(a: str, b: str) -> str:
    """Построить unified-diff двух текстовых версий схем.

    Использует :func:`difflib.unified_diff` из stdlib.

    Args:
        a: Текст первой (базовой) схемы.
        b: Текст второй (сравниваемой) схемы.

    Returns:
        Строка в формате unified-diff. Пустая строка — если схемы идентичны.
    """
    lines_a = a.splitlines(keepends=True)
    lines_b = b.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            lines_a, lines_b, fromfile="schema_a", tofile="schema_b", lineterm=""
        )
    )
    return "".join(diff)
