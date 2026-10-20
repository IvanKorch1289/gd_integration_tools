"""Cycle 169 regression: YAML `log: {level, message}` интерполяция.

DSL_AUDIT_CACHE_LOGGING_2026-10-20 §1.1-§1.2: до cycle 169
`RouteBuilder.log(level)` не принимал `message`. YAML с
`log: {level, ..., message: '...'}` не работал. Cycle 169 расширил
signature + добавил интерполяцию.
"""

from __future__ import annotations

import yaml

from src.backend.dsl.engine.processors.core import LogProcessor
from src.backend.dsl.yaml_loader import _build_pipeline


class TestYamlLogMessage:
    def test_yaml_log_with_message_works(self) -> None:
        """YAML `log: {level, message}` → создаёт `LogProcessor` с message."""
        spec_yaml = """
route_id: test_route
source: http:GET /test
steps:
  - log:
      level: info
      message: 'Order ${properties.order_id} processed'
"""
        spec = yaml.safe_load(spec_yaml)
        pipeline = _build_pipeline(spec)
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, LogProcessor)
        assert proc._level == "info"
        assert proc._message == "Order ${properties.order_id} processed"

    def test_yaml_log_without_message_legacy(self) -> None:
        """YAML `log: {level}` (без message) → legacy режим."""
        spec_yaml = """
route_id: test_route
source: http:GET /test
steps:
  - log:
      level: warning
"""
        spec = yaml.safe_load(spec_yaml)
        pipeline = _build_pipeline(spec)
        proc = pipeline.processors[0]
        assert isinstance(proc, LogProcessor)
        assert proc._level == "warning"
        assert proc._message == ""

    def test_yaml_log_default_level(self) -> None:
        """YAML `log: {}` (без level) → default level=info."""
        spec_yaml = """
route_id: test_route
source: http:GET /test
steps:
  - log: {}
"""
        spec = yaml.safe_load(spec_yaml)
        pipeline = _build_pipeline(spec)
        proc = pipeline.processors[0]
        assert proc._level == "info"


class TestYamlInfraLogWriteNotInWhitelist:
    """Cycle 169 discovery: `infra_log_write` задекларирован через
    `@processor(...)`, но НЕ доступен через YAML DSL whitelist.

    YAML `_apply_processor` использует `_is_allowed_processor` который
    ищет только публичные методы `RouteBuilder` (A2 whitelist). Метод
    `infra_log_write()` в `RouteBuilder` отсутствует → процессор
    зарегистрирован в registry но не интегрирован с builder.

    Для prod acceptance требуется:
    1. Добавить `infra_log_write(level, message)` метод в
    `RouteBuilder` (через `LazyProcessorMixin` или явный метод).
    2. Добавить integration-test на YAML → processor mapping.

    Пока — фиксируем, что YAML вызов падает с ValueError, чтобы
    regression был заметен.
    """

    def test_yaml_infra_log_write_rejected(self) -> None:
        """YAML `infra_log_write: {...}` → ValueError (нет в whitelist)."""
        spec_yaml = """
route_id: test_route
source: http:GET /test
steps:
  - infra_log_write:
      level: error
      message: 'Failed'
"""
        spec = yaml.safe_load(spec_yaml)
        import pytest

        with pytest.raises(ValueError, match="Unknown or forbidden"):
            _build_pipeline(spec)