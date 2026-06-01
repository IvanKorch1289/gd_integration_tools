"""DSL-шаг ``desktop_rpa`` — Windows desktop UI automation через worker.

Wave: ``[wave:s8/k3-rpa-windows-desktop]``. Делегирует выполнение в
``DesktopRpaClient``, который вызывает windows-worker sidecar.

Использование (Python builder)::

    builder.desktop_rpa(
        app="C:/Program Files/MyApp/app.exe",
        action="click",
        params={"selector": {"title": "OK"}, "button": "left"},
        to="property:rpa.last_action",
    )

YAML::

    - desktop_rpa:
        app: "C:/Program Files/MyApp/app.exe"
        action: type
        params:
          selector: {auto_id: "username"}
          text: "ivan"
        to: property:rpa.last_action
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange
    from src.backend.services.rpa.desktop_rpa_client import DesktopRpaClient

__all__ = ("DesktopRpaProcessor",)

_logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"click", "type", "screenshot"})


@processor(name="desktop_rpa")
class DesktopRpaProcessor(BaseProcessor):
    """Делегирует desktop-RPA action на windows-worker через REST.

    Args:
        app: Путь к exe или PID процесса.
        action: ``click`` / ``type`` / ``screenshot``.
        params: Параметры action (selector / text / backend / timeout —
            см. Pydantic-модели в windows-worker handler'е).
        to: Опц. путь записи ответа (``body.<field>`` / ``property:<name>``).
        name: Имя процессора для трейсов.
    """

    name = "desktop_rpa"

    def __init__(
        self,
        *,
        app: str,
        action: str,
        params: dict[str, Any] | None = None,
        to: str = "property:rpa.desktop_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or self.name)
        if action not in _VALID_ACTIONS:
            raise ValueError(
                f"desktop_rpa: action должен быть одним из {sorted(_VALID_ACTIONS)}, "
                f"получено {action!r}"
            )
        self._app = app
        self._action = action
        self._params = dict(params or {})
        # ``app`` всегда добавляется в payload — handler ожидает его в теле.
        self._params.setdefault("app", app)
        self._to = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Выполняет action через DesktopRpaClient из ExecutionContext."""
        client: DesktopRpaClient | None = getattr(context, "desktop_rpa_client", None)
        if client is None:
            app_state = getattr(context, "app_state", None)
            if app_state is not None:
                client = getattr(app_state, "desktop_rpa_client", None)
        if client is None:
            exchange.fail(
                "desktop_rpa: DesktopRpaClient не зарегистрирован "
                "(проверь lifespan / DI services/rpa/desktop_rpa_client.py)"
            )
            return

        try:
            payload = dict(self._params)
            payload["app"] = self._app
            result = await client.execute(self._action, payload)
        except Exception as exc:  # noqa: BLE001 — DSL-граница
            exchange.fail(f"desktop_rpa({self._action!r}) failed: {exc}")
            return

        self._write(exchange, result)

    def _write(self, exchange: "Exchange[Any]", value: Any) -> None:
        target = self._to
        if target.startswith("property:"):
            exchange.set_property(target[len("property:") :], value)
            return
        if target == "body":
            exchange.in_message.body = value
            return
        if target.startswith("body."):
            key = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
            body[key] = value
            exchange.in_message.body = body
            return
        exchange.set_property(target, value)
