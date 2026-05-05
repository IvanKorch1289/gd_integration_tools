"""DI-providers для invocation-сервисов (W22 техдолг).

FastAPI Depends-функции и singleton-аксессоры, через которые
``services/`` и ``entrypoints/`` получают доступ к
:class:`ReplyChannelRegistryProtocol` и :class:`Invoker`.

Размещены в ``core/di``, чтобы:

* ``services/execution/invoker.py`` мог резолвить registry без импорта
  из ``infrastructure/`` (нарушение Правила 4: services → infra);
* ``entrypoints/api/v1/endpoints/invocations.py`` и
  ``entrypoints/websocket/ws_invocations.py`` использовали
  ``Depends(...)`` вместо прямого импорта infra-имплементаций.

Реальные singletons (``ReplyChannelRegistry``, ``Invoker``) создаются
в composition root :func:`src.plugins.composition.di.register_app_state`
и кладутся в ``app.state.reply_registry`` / ``app.state.invoker``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.di.app_state import _get_from_app_state, app_state_singleton

if TYPE_CHECKING:
    from fastapi import Request, WebSocket

    from src.core.interfaces.invocation_reply import ReplyChannelRegistryProtocol
    from src.core.interfaces.invoker import Invoker as InvokerProtocol
    from src.core.interfaces.watermark_store import WatermarkStore

__all__ = (
    "get_reply_registry",
    "get_reply_registry_ws",
    "get_invoker_dep",
    "get_reply_registry_singleton",
    "get_invoker_singleton",
    "get_watermark_store_singleton",
    "get_watermark_store_optional",
)


async def get_reply_registry(request: "Request") -> "ReplyChannelRegistryProtocol":
    """FastAPI Depends: возвращает registry из ``request.app.state``."""
    return request.app.state.reply_registry


def get_reply_registry_ws(websocket: "WebSocket") -> "ReplyChannelRegistryProtocol":
    """WebSocket-эквивалент: registry из ``websocket.app.state``.

    FastAPI Depends ограниченно поддерживается в WebSocket-роутах,
    поэтому помощник синхронный и вызывается явно из обработчика.
    """
    return websocket.app.state.reply_registry


async def get_invoker_dep(request: "Request") -> "InvokerProtocol":
    """FastAPI Depends: возвращает :class:`Invoker` из ``request.app.state``."""
    return request.app.state.invoker


@app_state_singleton("reply_registry")
def get_reply_registry_singleton() -> "ReplyChannelRegistryProtocol":
    """Singleton-аксессор для non-request контекстов (DSL processors, scripts).

    Lazy-резолв из ``app.state.reply_registry``. Если registry ещё не
    зарегистрирован (``register_app_state`` не вызывался), декоратор
    бросит ``RuntimeError`` — вызывающая сторона должна обработать
    отсутствие реестра как опциональное.
    """
    raise RuntimeError(
        "reply_registry должен быть зарегистрирован через register_app_state()"
    )


@app_state_singleton("invoker")
def get_invoker_singleton() -> "InvokerProtocol":
    """Singleton-аксессор :class:`Invoker` для non-request контекстов.

    Lazy-резолв из ``app.state.invoker``. Factory здесь не задаётся:
    создание ``Invoker`` требует concrete ``ReplyChannelRegistry``,
    что нарушает layer policy для core/. Composition root в
    ``register_app_state`` обязан положить готовый Invoker в app.state.
    """
    raise RuntimeError("invoker должен быть зарегистрирован через register_app_state()")


@app_state_singleton("watermark_store")
def get_watermark_store_singleton() -> "WatermarkStore":
    """Singleton-аксессор :class:`WatermarkStore` (W14.5).

    Lazy-резолв из ``app.state.watermark_store``. Factory не задаётся,
    т.к. PG-реализация требует ``DatabaseSessionManager`` из infra-слоя
    (нарушение layer policy для core/). Composition root обязан положить
    готовый store в app.state.
    """
    raise RuntimeError(
        "watermark_store должен быть зарегистрирован через register_app_state()"
    )


def get_watermark_store_optional() -> "WatermarkStore | None":
    """Безопасный аксессор: возвращает ``None`` без зарегистрированного store.

    Используется в DSL-builder и unit-тестах, где app.state может быть не
    инициализирован. В отличие от :func:`get_watermark_store_singleton`
    не бросает ``RuntimeError`` — окно просто работает без durability.
    """
    return _get_from_app_state("watermark_store")
