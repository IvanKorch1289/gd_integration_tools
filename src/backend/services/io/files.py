"""Backward-compat shim для FileService (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.files.services.files``
(см. R-V15-16). Этот shim сохраняется на 1 minor-цикл и эмитит DeprecationWarning.

ADR-0457: объект отдаётся расширением через core-реестр ресурсов
(``get_extension_resource``) — статической зависимости ``src/ → extensions``
не остаётся (``tools/check_layers.py``). Атрибуты резолвятся лениво через
PEP 562 ``__getattr__``, поэтому импорт shim'а не тянет расширения.
``DeprecationWarning`` выдаётся и при импорте shim'а, и при обращении
к его атрибутам.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any

from src.backend.core.extension_registry import get_extension_resource

__all__ = ("FileService", "get_file_service")  # noqa: F822 — lazy __getattr__ exports

#: Ключ ресурса расширения ``files`` (домен / вид / имя).
_DOMAIN = "files"
_KIND = "service"
_NAME = "files"

_DEPRECATION_MESSAGE = (
    "src.backend.services.io.files устарел; используйте "
    "extensions.core_entities.files.services.files (R-V15-16)."
)

warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)


def __getattr__(name: str) -> Any:
    """Лениво отдаёт ``FileService`` / ``get_file_service`` из реестра расширений.

    Args:
        name: Имя запрашиваемого атрибута модуля.

    Returns:
        Класс ``FileService`` расширения либо геттер ``get_file_service``.

    Raises:
        AttributeError: запрошен неизвестный атрибут.

    """
    if name not in ("FileService", "get_file_service"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    getter = get_extension_resource(_DOMAIN, _KIND, _NAME)
    if name == "get_file_service":
        return getter
    # Класс лежит в модуле расширения, отдавшем геттер (identity сохраняется).
    service_module = importlib.import_module(getter.__module__)
    return getattr(service_module, "FileService")
