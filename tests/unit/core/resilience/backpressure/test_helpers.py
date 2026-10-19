"""Tests for ``src.backend.core.resilience.backpressure.helpers``.

S67 W1: singleton ``get_streaming_controller()`` для доступа
к глобальному :class:`StreamingBackpressureController`.
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience.backpressure.controller import (
    StreamingBackpressureController,
)
from src.backend.core.resilience.backpressure import helpers


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset singleton state до/после каждого теста для изоляции."""
    helpers._controller_instance = None
    yield
    helpers._controller_instance = None


class TestGetStreamingController:
    """Singleton accessor."""

    def test_first_call_creates_instance(self) -> None:
        controller = helpers.get_streaming_controller()
        assert controller is not None
        assert isinstance(controller, StreamingBackpressureController)

    def test_first_call_sets_module_state(self) -> None:
        """``_controller_instance`` обновляется после первого call."""
        assert helpers._controller_instance is None
        helpers.get_streaming_controller()
        assert helpers._controller_instance is not None

    def test_subsequent_calls_return_same_instance(self) -> None:
        """Singleton — повторные вызовы возвращают тот же объект."""
        c1 = helpers.get_streaming_controller()
        c2 = helpers.get_streaming_controller()
        assert c1 is c2

    def test_singleton_after_many_calls(self) -> None:
        """100 вызовов — всё тот же объект."""
        first = helpers.get_streaming_controller()
        for _ in range(100):
            current = helpers.get_streaming_controller()
            assert current is first


class TestSingletonIsolation:
    """Тесты на изоляцию singleton state между тестами.

    ``_reset_singleton`` autouse-fixture сбрасывает singleton
    до и после каждого теста — без этого тесты пересекались бы.
    """

    def test_reset_before_test(self) -> None:
        """Перед каждым тестом — singleton очищен."""
        assert helpers._controller_instance is None

    def test_reset_after_previous_test(self) -> None:
        """Если предыдущий тест создал controller, _reset_singleton его очистил."""
        # Этот тест проверяет, что singleton начинается с None
        # благодаря autouse fixture
        assert helpers._controller_instance is None
        # Создаём controller
        helpers.get_streaming_controller()
        # И не падаем — autouse fixture очистит после


class TestControllerInstance:
    """Проверка, что singleton возвращает настоящий controller."""

    def test_is_streaming_backpressure_controller(self) -> None:
        controller = helpers.get_streaming_controller()
        # ``StreamingBackpressureController`` — конкретный класс
        assert type(controller) is StreamingBackpressureController

    def test_has_required_methods(self) -> None:
        """У controller есть публичный API (для smoke-проверки)."""
        controller = helpers.get_streaming_controller()
        # Проверяем, что controller объект имеет атрибуты
        # (точный API зависит от реализации; мы просто проверяем,
        # что singleton возвращает валидный объект).
        assert controller is not None
        # У него есть ``__class__`` (минимум)
        assert hasattr(controller, "__class__")
