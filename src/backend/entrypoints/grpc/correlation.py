"""Helpers для propagation correlation_id через gRPC metadata (S17 K3 W3 D12).

Вынесено из ``grpc_server.py`` в отдельный модуль, чтобы тесты могли
импортировать helper без подъёма protobuf-stubs (которые требуют
sys.path-magic для top-level ``invoker_pb2`` импортов).
"""

from __future__ import annotations

from typing import Any

__all__ = ("GRPC_CORRELATION_ID_KEY", "extract_correlation_id_from_grpc_context")

# gRPC спецификация требует lowercase ASCII для текстовых metadata keys
# (binary keys имеют суффикс ``-bin``). Браузеры/клиенты могут прислать
# любой case — matching выполняется регистро-нечувствительно.
GRPC_CORRELATION_ID_KEY = "x-correlation-id"


def extract_correlation_id_from_grpc_context(context: Any) -> str:
    """Извлечь correlation_id из incoming gRPC ``invocation_metadata``.

    Возвращает пустую строку, если context отсутствует или metadata не
    содержит ``x-correlation-id``. Безопасно для тестов с MagicMock
    (отсутствие ``invocation_metadata`` → пустая строка).

    Поддерживает два формата metadata:

    * legacy ``list[tuple[str, str]]`` (старый grpc.aio API);
    * современный ``list[Metadata entries]`` с атрибутами ``.key``/``.value``.

    Args:
        context: gRPC ``ServicerContext`` (либо ``None`` / mock без метода).

    Returns:
        Значение ``x-correlation-id`` или ``""``, если не найдено.
    """
    if context is None:
        return ""
    invocation_metadata = getattr(context, "invocation_metadata", None)
    if invocation_metadata is None:
        return ""
    try:
        metadata = invocation_metadata()
    except TypeError:
        return ""
    if metadata is None:
        return ""
    for entry in metadata:
        key = getattr(entry, "key", None)
        value = getattr(entry, "value", None)
        if key is None and isinstance(entry, tuple) and len(entry) == 2:
            key, value = entry
        if key is None:
            continue
        if str(key).lower() == GRPC_CORRELATION_ID_KEY:
            return str(value) if value else ""
    return ""
