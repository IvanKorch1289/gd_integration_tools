"""ToolRegistry — реестр AI-инструментов с автогенерацией из сервисов.

Реестр решает три задачи:
  1. Регистрация публичных методов сервиса как AI-инструментов
     через интроспекцию сигнатуры (``from_service``).
  2. Загрузка пользовательских инструментов из плагин-файлов
     (``from_plugin_file``), где функции помечены ``@agent_tool``.
  3. Экспозиция списка инструментов через REST
     (``GET /api/v1/ai/tools``) и CLI (``manage.py list-tools``).

Формат ``AgentTool``:
  * ``id`` — уникальное имя ``<prefix>.<method>``;
  * ``description`` — из docstring метода/функции (русский язык);
  * ``parameters`` — JSON-schema параметров (by type hints);
  * ``callable`` — awaitable-функция вызова инструмента.

Интеграция с LangChain/LangGraph выполняется отдельно в
``src/services/ai/ai_graph.py`` — реестр лишь формирует описание.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.backend.core.di import app_state_singleton

__all__ = ("AgentTool", "ToolRegistry", "agent_tool", "get_tool_registry")

logger = logging.getLogger("services.ai.tools")


_AGENT_TOOL_FLAG = "__agent_tool__"

_SIMPLE_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    bytes: "string",
}


@dataclass(slots=True)
class AgentTool:
    """Описание AI-инструмента, готовое к использованию агентом.

    Атрибуты:
        id: Уникальный идентификатор (``prefix.method``).
        name: Короткое имя инструмента.
        description: Текстовое описание (из docstring).
        parameters: JSON-schema входных параметров.
        callable: Awaitable-функция выполнения.
        metadata: Произвольные дополнительные поля.
    """

    id: str
    name: str
    description: str
    parameters: dict[str, Any]
    callable: Callable[..., Awaitable[Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализует инструмент в JSON-совместимый dict.

        Returns:
            Словарь без ``callable`` (его нельзя сериализовать).
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "metadata": self.metadata,
        }


def agent_tool(
    *, name: str | None = None, description: str | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Декоратор для пометки функции как AI-инструмента.

    Функции, помеченные этим декоратором, автоматически собираются
    ``ToolRegistry.from_plugin_file``.

    Args:
        name: Переопределённое имя инструмента (по умолчанию —
            имя функции).
        description: Переопределённое описание (по умолчанию —
            первая строка docstring).

    Returns:
        Декоратор, не модифицирующий поведение функции.

    Пример::

        @agent_tool(name="sum_two")
        async def add(a: int, b: int) -> int:
            \"\"\"Складывает два числа.\"\"\"
            return a + b
    """

    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, _AGENT_TOOL_FLAG, {"name": name, "description": description})
        return fn

    return _wrap


def _snake_case(name: str) -> str:
    """Преобразует CamelCase в snake_case.

    Args:
        name: Исходное имя класса или функции.

    Returns:
        Имя в snake_case.
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _json_type(annotation: Any) -> str:
    """Сопоставляет Python-аннотацию с JSON-schema типом.

    Args:
        annotation: Type annotation параметра.

    Returns:
        Строковое имя JSON-schema типа (по умолчанию ``string``).
    """
    origin = getattr(annotation, "__origin__", annotation)
    if origin in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[origin]
    if annotation in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[annotation]
    return "string"


def _build_parameters(fn: Callable[..., Any]) -> dict[str, Any]:
    """Строит JSON-schema параметров по сигнатуре функции.

    Отбрасывает параметры ``self`` и ``cls``. Тип берётся из
    аннотации; обязательными считаются параметры без default.

    Args:
        fn: Функция (method/async function).

    Returns:
        JSON-schema вида ``{"type": "object", "properties": {...}, "required": [...]}``.
    """
    sig = inspect.signature(fn)
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        properties[pname] = {"type": _json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _extract_description(fn: Callable[..., Any]) -> str:
    """Возвращает первую непустую строку docstring функции.

    Args:
        fn: Функция/метод.

    Returns:
        Краткое описание или пустая строка, если docstring нет.
    """
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _is_public_method(name: str, obj: Any) -> bool:
    """Фильтр публичных методов сервиса.

    Args:
        name: Имя атрибута класса.
        obj: Значение атрибута.

    Returns:
        ``True`` если это публичная async/sync функция.
    """
    if name.startswith("_"):
        return False
    return inspect.iscoroutinefunction(obj) or inspect.isfunction(obj)


def _ensure_awaitable(fn: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Оборачивает синхронную функцию в awaitable.

    Args:
        fn: Sync или async callable.

    Returns:
        Awaitable-обёртка.
    """
    if inspect.iscoroutinefunction(fn):
        return fn

    async def _runner(*args: Any, **kwargs: Any) -> Any:
        """Асинхронный raw-вызов исходной функции."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    return _runner


class ToolRegistry:
    """Реестр AI-инструментов.

    Потокобезопасен на уровне asyncio (словарь + lock не требуется,
    т.к. регистрация идёт в startup/lifespan). Предоставляет три
    источника наполнения: методы сервиса, plugin-файл, прямая
    регистрация.

    Атрибуты:
        _tools: ``{id: AgentTool}``.
    """

    def __init__(self) -> None:
        """Создаёт пустой реестр."""
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> AgentTool:
        """Регистрирует инструмент напрямую.

        Args:
            tool: Готовое описание ``AgentTool``.

        Returns:
            Зарегистрированный инструмент.
        """
        self._tools[tool.id] = tool
        logger.debug("agent_tool_registered: %s", tool.id)
        return tool

    def get(self, tool_id: str) -> AgentTool | None:
        """Возвращает инструмент по ``id`` или ``None``.

        Args:
            tool_id: Уникальный идентификатор.

        Returns:
            Зарегистрированный инструмент или ``None``.
        """
        return self._tools.get(tool_id)

    def list(self) -> list[AgentTool]:
        """Список всех зарегистрированных инструментов.

        Returns:
            Отсортированный по ``id`` список.
        """
        return sorted(self._tools.values(), key=lambda t: t.id)

    def clear(self) -> None:
        """Очищает реестр (используется в тестах/hot-reload)."""
        self._tools.clear()

    def from_service(
        self,
        service_cls: type | Any,
        methods: list[str] | None = None,
        prefix: str | None = None,
        policy: dict[str, Any] | None = None,
    ) -> list[AgentTool]:
        """Регистрирует публичные методы сервиса как AI-инструменты.

        Принимает класс или экземпляр. Для класса инстанцирует его
        через фабрику-заглушку, если требуется вызов (``callable``
        инструмента использует bound-метод экземпляра).

        Args:
            service_cls: Класс сервиса либо готовый экземпляр.
            methods: Список имён методов; ``None`` — все публичные.
            prefix: Префикс ``id`` инструмента; ``None`` —
                snake_case имени класса.
            policy: Политика доступа (агентам/ролям). Сохраняется
                в ``metadata.policy``.

        Returns:
            Список зарегистрированных ``AgentTool``.

        Пример::

            reg.from_service(OrderService, methods=["get", "list"])
            # → order_service.get, order_service.list
        """
        instance = service_cls if not inspect.isclass(service_cls) else service_cls()
        cls = instance.__class__
        prefix = prefix or _snake_case(cls.__name__)
        selected = methods or [
            name
            for name, attr in inspect.getmembers(cls)
            if _is_public_method(name, attr)
        ]
        registered: list[AgentTool] = []
        for method_name in selected:
            raw = getattr(cls, method_name, None)
            if raw is None or not _is_public_method(method_name, raw):
                continue
            bound = getattr(instance, method_name)
            tool_id = f"{prefix}.{method_name}"
            tool = AgentTool(
                id=tool_id,
                name=method_name,
                description=_extract_description(raw),
                parameters=_build_parameters(raw),
                callable=_ensure_awaitable(bound),
                metadata={
                    "source": "service",
                    "service": cls.__name__,
                    "policy": policy or {},
                },
            )
            self.register(tool)
            registered.append(tool)
        logger.info(
            "tool_registry_from_service: %s → %d tools", cls.__name__, len(registered)
        )
        return registered

    def from_plugin_file(self, path: str | Path) -> list[AgentTool]:
        """Загружает ``@agent_tool``-функции из плагин-файла.

        Импортирует файл по явному пути (без его установки в sys.path),
        собирает все функции с атрибутом ``__agent_tool__`` и регистрирует
        их как инструменты. Имя инструмента = ``plugin.<имя файла>.<функция>``.

        Args:
            path: Путь к ``.py``-файлу плагина.

        Returns:
            Список зарегистрированных ``AgentTool``.

        Raises:
            FileNotFoundError: Плагин-файл не существует.
            ImportError: Не удалось импортировать файл.
        """
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"Plugin file not found: {file_path}")

        module_name = f"agent_tools_plugin_{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin: {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        prefix = f"plugin.{file_path.stem}"
        registered: list[AgentTool] = []
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            meta = getattr(obj, _AGENT_TOOL_FLAG, None)
            if meta is None or not callable(obj):
                continue
            tool_name = meta.get("name") or attr_name
            tool_id = f"{prefix}.{tool_name}"
            description = meta.get("description") or _extract_description(obj)
            tool = AgentTool(
                id=tool_id,
                name=tool_name,
                description=description,
                parameters=_build_parameters(obj),
                callable=_ensure_awaitable(obj),
                metadata={"source": "plugin", "path": str(file_path)},
            )
            self.register(tool)
            registered.append(tool)
        logger.info(
            "tool_registry_from_plugin_file: %s → %d tools", file_path, len(registered)
        )
        return registered


@app_state_singleton("ai_tool_registry", factory=ToolRegistry)
def get_tool_registry() -> ToolRegistry:
    """Возвращает singleton ``ToolRegistry``."""
