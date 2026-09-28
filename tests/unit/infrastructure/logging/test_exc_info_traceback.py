"""Регрессия: ``exc_info`` должен прикреплять traceback к записи лога.

До фикса (HEAD 6c27c02c2) цепочка процессоров structlog в
``StructlogGraylogBackend.configure()`` не содержала
``structlog.processors.format_exc_info``. Следствие: ключ ``exc_info``
оставался обычным полем event_dict и рендерился как ``"exc_info": true`` —
без единой строки traceback, и ``LogRecord.exc_info`` тоже был пуст.
То есть ни ``logger.error(..., exc_info=True)``, ни ``logger.exception()``
не давали стека трейса ни в одном из бэкендов (JSON/GELF/файл).

Затронуто 116 ``exc_info``-вызовов и 138 ``.exception()``-вызовов в ``src/``.

Тесты проверяют сквозной результат (отрендеренную запись), а не то, что
kwarg дошёл до structlog — прежние тесты ``test_s60_w1_compat_shim.py``
проверяли только проксирование kwarg и были зелёными при этом дефекте.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
import structlog

from src.backend.infrastructure.logging.factory import (
    configure_logging,
    get_logger,
    shutdown_logging,
)

# ---------------------------------------------------------------------- helpers


class _CaptureHandler(logging.Handler):
    """Handler, собирающий отрендеренные записи."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # Именно self.format(), а не getMessage(): ProcessorFormatter
        # подставляет отрендеренный event_dict в record.msg только при
        # форматировании. getMessage() вернул бы dict-repr.
        self.messages.append(self.format(record))


@pytest.fixture
def captured() -> Any:
    """Настраивает реальный structlog-бэкенд и перехватывает вывод root.

    Используется production-путь ``configure_logging()`` → factory →
    ``StructlogGraylogBackend.configure()``, а не ручная сборка цепочки:
    тест обязан падать, если процессор выпадет из production-конфигурации.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    configure_logging()

    handler = _CaptureHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ]
        )
    )
    root.addHandler(handler)

    yield handler

    root.removeHandler(handler)
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    shutdown_logging()


def _last_event(handler: _CaptureHandler) -> dict[str, Any]:
    """Разбирает последнюю отрендеренную JSON-запись."""
    assert handler.messages, "ни одной записи не отрендерено"
    return json.loads(handler.messages[-1])


# ---------------------------------------------------------------------- tests


def test_error_with_exc_info_true_attaches_traceback(captured: _CaptureHandler) -> None:
    """``logger.error(..., exc_info=True)`` → traceback в записи."""
    logger = get_logger("exc-info-test")

    try:
        raise ValueError("exc-info-marker-42")
    except ValueError:
        logger.error("operation failed: %s", "downstream", exc_info=True)

    event = _last_event(captured)
    assert "exc-info-marker-42" in event.get("exception", "")
    assert "Traceback" in event.get("exception", "")
    assert "ValueError" in event.get("exception", "")


def test_exception_method_attaches_traceback(captured: _CaptureHandler) -> None:
    """``logger.exception()`` → traceback в записи (не только exc_info=True)."""
    logger = get_logger("exc-info-test")

    try:
        raise RuntimeError("exception-method-marker")
    except RuntimeError:
        logger.exception("handler blew up")

    event = _last_event(captured)
    assert "exception-method-marker" in event.get("exception", "")
    assert "RuntimeError" in event.get("exception", "")


def test_exc_info_true_outside_except_block_is_safe(captured: _CaptureHandler) -> None:
    """``exc_info=True`` без активного исключения не роняет логирование.

    Guards against a regression of a different kind: часть вызовов в ``src/``
    передаёт ``exc_info=True`` вне ``except``-блока. Такой вызов обязан
    остаться no-op, а не поднять ``TypeError`` из процессора.
    """
    logger = get_logger("exc-info-test")

    logger.error("no active exception here", exc_info=True)

    event = _last_event(captured)
    assert "no active exception here" in event["event"]
    assert "exception" not in event, "не должно быть выдуманного traceback"


def test_plain_error_has_no_exception_key(captured: _CaptureHandler) -> None:
    """Контроль: запись без exc_info не получает ключ ``exception``."""
    logger = get_logger("exc-info-test")

    logger.info("nothing failed")

    event = _last_event(captured)
    assert "exception" not in event
    assert "exc_info" not in event


def test_traceback_passes_through_pii_redaction(captured: _CaptureHandler) -> None:
    """Текст traceback проходит ту же PII-редакцию, что и остальные поля.

    ``format_exc_info`` стоит ДО ``_mask_pii`` в цепочке — значит адрес
    в тексте исключения маскируется. Иначе traceback стал бы обходным
    путём утечки PII в Graylog.
    """
    logger = get_logger("exc-info-test")

    try:
        raise ValueError("contact me at pii-marker@example.com")
    except ValueError:
        logger.error("failed", exc_info=True)

    event = _last_event(captured)
    exception_text = event.get("exception", "")
    assert "pii-marker@example.com" not in exception_text
    assert "<email>" in exception_text
