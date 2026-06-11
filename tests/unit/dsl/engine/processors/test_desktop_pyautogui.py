"""Unit-тесты для DesktopPyAutoGUIProcessor (Sprint 36).

Тестирует:
- screenshot, click, type_text, press_key actions
- graceful degradation при отсутствии pyautogui
- валидацию параметров
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.desktop_pyautogui import (
    DesktopPyAutoGUIProcessor,
)


def _make_exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body=None, headers={}))


class TestDesktopPyAutoGUIProcessor:
    """Тесты для DesktopPyAutoGUIProcessor."""

    @pytest.mark.asyncio
    async def test_screenshot(self) -> None:
        """Screenshot action."""
        proc = DesktopPyAutoGUIProcessor(action="screenshot")
        exchange = _make_exchange()

        mock_img = MagicMock()
        with patch.dict(
            "sys.modules",
            {"pyautogui": MagicMock(screenshot=MagicMock(return_value=mock_img))},
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("desktop_result") == {
            "action": "screenshot",
            "result": True,
        }

    @pytest.mark.asyncio
    async def test_click_with_coords(self) -> None:
        """Click с координатами."""
        proc = DesktopPyAutoGUIProcessor(action="click", x=100, y=200)
        exchange = _make_exchange()

        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            await proc.process(exchange, MagicMock())

        mock_pyautogui.click.assert_called_once_with(100, 200, duration=0.25)
        assert exchange.properties.get("desktop_result") == {
            "action": "click",
            "result": True,
        }

    @pytest.mark.asyncio
    async def test_type_text(self) -> None:
        """Type text action."""
        proc = DesktopPyAutoGUIProcessor(action="type_text", text="hello")
        exchange = _make_exchange()

        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            await proc.process(exchange, MagicMock())

        mock_pyautogui.typewrite.assert_called_once_with("hello", interval=0.01)

    @pytest.mark.asyncio
    async def test_press_key(self) -> None:
        """Press key action."""
        proc = DesktopPyAutoGUIProcessor(action="press_key", key="enter")
        exchange = _make_exchange()

        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            await proc.process(exchange, MagicMock())

        mock_pyautogui.press.assert_called_once_with("enter")

    @pytest.mark.asyncio
    async def test_missing_pyautogui(self) -> None:
        """Graceful degradation при отсутствии pyautogui."""
        proc = DesktopPyAutoGUIProcessor(action="screenshot")
        exchange = _make_exchange()

        with patch.dict("sys.modules", {"pyautogui": None}):
            await proc.process(exchange, MagicMock())

        assert exchange.status == ExchangeStatus.failed
        assert "pyautogui not installed" in (exchange.error or "")

    @pytest.mark.asyncio
    async def test_type_text_missing_text(self) -> None:
        """type_text без text — exchange.fail."""
        proc = DesktopPyAutoGUIProcessor(action="type_text")
        exchange = _make_exchange()

        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            await proc.process(exchange, MagicMock())

        assert exchange.status == ExchangeStatus.failed

    def test_invalid_action(self) -> None:
        """Невалидный action — ValueError при конструировании."""
        with pytest.raises(ValueError, match="action must be one of"):
            DesktopPyAutoGUIProcessor(action="invalid")

    def test_to_spec(self) -> None:
        """Сериализация в spec."""
        proc = DesktopPyAutoGUIProcessor(
            action="click", x=10, y=20, duration=0.5, result_property="r"
        )
        spec = proc.to_spec()
        assert spec == {
            "desktop_pyautogui": {
                "action": "click",
                "x": 10,
                "y": 20,
                "duration": 0.5,
                "result_property": "r",
            }
        }
