"""Desktop automation processor via pyautogui (Linux/macOS).

Sprint 36: cross-platform desktop automation для dev-окружений.
Windows использует dedicated windows-worker sidecar (desktop_rpa.py).

Lazy-import ``pyautogui`` — отсутствие пакета даёт graceful degradation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry.processor import processor

__all__ = ("DesktopPyAutoGUIProcessor",)

_logger = get_logger("dsl.desktop_pyautogui")

_VALID_ACTIONS = frozenset({"screenshot", "click", "type_text", "press_key", "move"})


@processor(
    "desktop_pyautogui",
    namespace="core",
    capabilities=("rpa.desktop.automate",),
    tags=["rpa", "desktop"],
)
class DesktopPyAutoGUIProcessor(BaseProcessor):
    """Cross-platform desktop automation via pyautogui.

    Usage (Python builder)::

        builder.desktop_automate("screenshot")
        builder.desktop_automate("click", x=100, y=200)
        builder.desktop_automate("type_text", text="Hello World")
        builder.desktop_automate("press_key", key="enter")

    Usage (YAML)::

        - desktop_pyautogui:
            action: click
            x: 100
            y: 200
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        action: str,
        *,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        key: str | None = None,
        duration: float = 0.25,
        result_property: str = "desktop_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"desktop_pyautogui:{action}")
        if action not in _VALID_ACTIONS:
            raise ValueError(
                f"desktop_pyautogui: action must be one of {sorted(_VALID_ACTIONS)}, "
                f"got {action!r}"
            )
        self._action = action
        self._x = x
        self._y = y
        self._text = text
        self._key = key
        self._duration = duration
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет desktop RPA-действие через pyautogui (screenshot/click/type/...).

        Поддерживаемые действия: ``screenshot``, ``click``, ``type_text``,
        ``press_key``, ``move``. Координаты, текст и клавиши берутся из
        параметров. Результат (success-флаг) записывается в свойство
        ``result_property``.

        Args:
            exchange: Текущий exchange; результат — в свойстве
                ``result_property`` (default: ``pyautogui_result``).
            context: Контекст выполнения маршрута.
        """
        try:
            import pyautogui
        except ImportError:
            exchange.fail("pyautogui not installed. Install: uv sync --extra rpa")
            return

        try:
            result: Any = None
            if self._action == "screenshot":
                result = pyautogui.screenshot()
            elif self._action == "click":
                if self._x is not None and self._y is not None:
                    result = pyautogui.click(self._x, self._y, duration=self._duration)
                else:
                    result = pyautogui.click(duration=self._duration)
            elif self._action == "type_text":
                if self._text is None:
                    exchange.fail("desktop_pyautogui: text required for type_text")
                    return
                result = pyautogui.typewrite(self._text, interval=0.01)
            elif self._action == "press_key":
                if self._key is None:
                    exchange.fail("desktop_pyautogui: key required for press_key")
                    return
                result = pyautogui.press(self._key)
            elif self._action == "move":
                if self._x is not None and self._y is not None:
                    result = pyautogui.moveTo(self._x, self._y, duration=self._duration)
                else:
                    exchange.fail("desktop_pyautogui: x and y required for move")
                    return

            exchange.set_property(
                self._result_property,
                {"action": self._action, "result": result is not None},
            )
        except Exception as exc:
            exchange.fail(f"desktop_pyautogui({self._action!r}) failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"action": self._action}
        if self._x is not None:
            spec["x"] = self._x
        if self._y is not None:
            spec["y"] = self._y
        if self._text is not None:
            spec["text"] = self._text
        if self._key is not None:
            spec["key"] = self._key
        if self._duration != 0.25:
            spec["duration"] = self._duration
        if self._result_property != "desktop_result":
            spec["result_property"] = self._result_property
        return {"desktop_pyautogui": spec}
