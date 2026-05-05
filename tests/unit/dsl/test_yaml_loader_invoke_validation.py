"""F.2 B1 — Валидация mode для invoke в yaml_loader.

Проверяет, что при загрузке YAML-маршрута с невалидным `mode`
поднимается ValueError с понятным контекстом (имя action и список
допустимых значений), а не голый ``'foo' is not a valid InvocationMode``.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def test_invoke_invalid_mode_yaml_message() -> None:
    """Bad mode в YAML должен дать сообщение со списком допустимых режимов."""
    yaml_str = """
route_id: test.invoke.bad_mode
source: test
processors:
  - invoke:
      action: orders.add
      mode: bogus
"""
    with pytest.raises(ValueError) as exc_info:
        load_pipeline_from_yaml(yaml_str)
    msg = str(exc_info.value)
    assert "invoke" in msg
    assert "bogus" in msg
    # Допустимые значения должны фигурировать в сообщении.
    for expected in ("sync", "async-api", "async-queue"):
        assert expected in msg, f"missing {expected!r} in error: {msg}"


def test_invoke_valid_mode_loads() -> None:
    """Корректный YAML с валидным mode — загружается без ошибок."""
    yaml_str = """
route_id: test.invoke.ok
source: test
processors:
  - invoke:
      action: orders.add
      mode: async-api
      timeout: 5
      correlation_id: corr-42
"""
    pipeline = load_pipeline_from_yaml(yaml_str)
    assert pipeline.route_id == "test.invoke.ok"


def test_invoke_invalid_timeout_yaml_message() -> None:
    """B2: невалидный timeout в YAML — типизированная ошибка."""
    yaml_str = """
route_id: test.invoke.bad_timeout
source: test
processors:
  - invoke:
      action: orders.add
      timeout: -3
"""
    with pytest.raises(ValueError) as exc_info:
        load_pipeline_from_yaml(yaml_str)
    msg = str(exc_info.value)
    assert "timeout" in msg
