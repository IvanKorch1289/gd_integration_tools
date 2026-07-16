"""S175 Phase 3: _resolve helper — restored from original entity.py.

Parallel WIP создал entity/ subpackage (Phase 2), но забыл добавить
``_resolve`` helper (функция использовалась в audit.py и других местах).
Этот файл — минимальный patch для восстановления helper-функции.
Удалить в S175.5+ после физического разделения entity subpackage.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.exchange import Exchange


def _walk(node: Any, parts: list[str]) -> Any:
    """Рекурсивный walk по dict через list of parts.

    Args:
        node: Текущий узел (dict или leaf value).
        parts: Список имён полей для navigation.

    Returns:
        Value по пути или ``None`` если путь не существует.
    """
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _resolve(exchange: Exchange[Any], expression: str | None) -> Any:
    """Извлекает значение из exchange по ``namespace.path``.

    Поддерживаемые namespaces (по префиксу):
    - ``body.<path>`` → ``exchange.in_message.body``
    - ``properties.<path>`` → ``exchange.properties``
    - ``result.<path>`` → ``exchange.get_property("action_result")``
    - ``header.<name>`` → ``exchange.in_message.headers``
    - bare path → ``exchange.properties`` (legacy fallback)

    Args:
        exchange: Текущий exchange для resolution.
        expression: Path-expression (``"body.user.id"`` и т.п.).

    Returns:
        Resolved value или ``None`` если path отсутствует.
    """
    if not expression:
        return None
    if expression.startswith("header."):
        return exchange.in_message.headers.get(expression.removeprefix("header."))
    parts = expression.split(".")
    head, tail = parts[0], parts[1:]
    if head == "body":
        body = exchange.in_message.body
        if isinstance(body, dict):
            return _walk(body, tail) if tail else body
        return body if not tail else None
    if head == "properties":
        return _walk(exchange.properties, tail) if tail else exchange.properties
    if head == "result":
        result = exchange.get_property("action_result")
        return _walk(result, tail) if tail else result
    return _walk(exchange.properties, parts)