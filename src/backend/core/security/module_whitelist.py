"""Общая проверка whitelist модулей для динамического импорта handlers.

Helper намеренно отвечает только за сопоставление имени модуля. Strict-режим,
capability checks и audit events остаются ответственностью вызывающего слоя.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

__all__ = ("EmptyWhitelistMode", "validate_module_whitelist")

EmptyWhitelistMode = Literal["allow", "error"]


def validate_module_whitelist(
    module_name: str,
    whitelist: Iterable[str],
    *,
    context: str = "module whitelist",
    denied_suffix: str = "",
    empty_mode: EmptyWhitelistMode = "error",
    empty_error: type[Exception] = PermissionError,
    empty_message: str | None = None,
) -> None:
    """Проверяет модуль по exact- и namespace-записям ``prefix.*``.

    Args:
        module_name: Полное имя модуля для проверки.
        whitelist: Точные имена модулей или шаблоны namespace ``.*``.
        context: Префикс для текста отказа.
        denied_suffix: Необязательный суффикс вызывающего слоя в тексте отказа.
        empty_mode: ``"allow"`` сохраняет явный dev fallback;
            ``"error"`` отклоняет пустой whitelist.
        empty_error: Тип исключения при ``empty_mode="error"``.
        empty_message: Необязательный текст ошибки для пустого whitelist.

    Raises:
        PermissionError: Если модуль запрещён или пустой whitelist требует
            ``PermissionError``.
        ValueError: Если пустой whitelist требует ``ValueError``.
    """
    whitelist_set = set(whitelist)
    if not whitelist_set:
        if empty_mode == "allow":
            return
        message = empty_message or f"{context}: empty whitelist"
        raise empty_error(message)

    if module_name in whitelist_set:
        return

    for entry in whitelist_set:
        if entry.endswith(".*") and module_name.startswith(entry[:-2] + "."):
            return

    raise PermissionError(
        f"{context}: module {module_name!r} not in whitelist{denied_suffix}",
    )
