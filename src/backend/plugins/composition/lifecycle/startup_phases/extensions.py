"""Startup-фаза: pre-load ресурсов расширений (волна 36, P2-1).

Зачем
----
До волны 36 ресурсы расширений подгружались **лениво** — при первом
обращении к core-реестру (ADR-0457). Это означало:

* тяжёлый импорт расширений (~3 с) попадал в **request-path** — первый
  запрос платил за все расширения;
* сломанное расширение обнаруживалось уже в рантайме (500 у потребителя),
  а не на старте.

Фаза загружает расширения на старте приложения: импорт уходит из
request-path, а поломка расширения видна в логах старта.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.backend.core.logging import get_logger

__all__ = ("phase_extension_resources",)

logger = get_logger(__name__)


async def phase_extension_resources(app: FastAPI) -> None:  # noqa: ARG001
    """Загрузить ресурсы расширений и сообщить о состоянии загрузки.

    Ошибка загрузки **не** роняет старт: одно сломанное расширение не
    должно блокировать приложение (принцип best-effort startup). Но
    ошибка попадает в warning-лог вместе со списком загруженных доменов —
    поломка видна сразу, а не по 500-му в рантайме.

    Args:
        app: Экземпляр FastAPI (не используется — фаза глобальная).

    """
    from src.backend.core.extension_registry import (
        get_extension_load_errors,
        get_extension_registry,
        load_extension_resources,
    )

    load_extension_resources()

    domains = get_extension_registry().domains()
    logger.info(
        "Ресурсы расширений загружены: домены=%s",
        ", ".join(domains) if domains else "—",
    )

    errors = get_extension_load_errors()
    if errors:
        logger.warning(
            "Расширения загрузились с ошибками (%d): %s",
            len(errors),
            "; ".join(
                f"{module}: {reason}" for module, reason in sorted(errors.items())
            ),
        )
