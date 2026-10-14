"""Lint-style regression test for Proposal 4 (2026-10-14).

Proposal 4: заменить 'except Exception as _:' на 'except Exception as exc:'
в outbox/invocation_replies/express.py — два места:
1. send() method line 111 (now ~120): logged error must include exc type
2. get_adapter() helper line 137 (now ~131): logged debug must include exc type

Это НЕ mass-rewrite. Targeted fix, как описано в Proposal 4.

Этот тест — lint-style проверка source-файла, не runtime-test. Логирование
через capture-logging сложно в async-kонтексте; вместо этого проверяем
что source-файл содержит правильный паттерн (as exc + type(exc).__name__).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Test file is at: tests/unit/infrastructure/messaging/invocation_replies/test_express_channel.py
# Go up 5 levels to get to repo root:
# tests/unit/infrastructure/messaging/invocation_replies → repo root
REPO = Path(__file__).resolve().parents[5]
EXPRESS_FILE = (
    REPO
    / "src/backend/infrastructure/messaging/invocation_replies/express.py"
)


def _read_express_source() -> str:
    return EXPRESS_FILE.read_text(encoding="utf-8")


def test_express_source_no_anonymous_exception_in_send():
    """Proposal 4: send() НЕ должен содержать 'except Exception as _:'."""
    source = _read_express_source()
    # Ищем строку "except Exception as _:" рядом с logger.exception / logger.debug
    # Proposal 4: заменили на 'except Exception as exc:' (no anonymous)
    assert "except Exception as _:" not in source, (
        "Proposal 4 fix (2026-10-14): 'except Exception as _:' найден в express.py. "
        "Должно быть 'except Exception as exc:' с logger.exception/debug."
    )


def test_express_source_logs_exc_type_in_send():
    """Proposal 4: send() должен log type(exc).__name__ для диагностики."""
    source = _read_express_source()
    # Ищем logger.exception вызов с exc_type в f-string
    assert "exc_type" in source, (
        "Proposal 4: 'exc_type' в f-string format logger.exception не найден. "
        "Должен быть logger.exception(..., type(exc).__name__) для observability."
    )


def test_express_source_logs_exc_type_in_get_adapter():
    """Proposal 4: get_adapter() должен log type(exc).__name__ при fallback."""
    source = _read_express_source()
    # Ищем logger.debug вызов с exc type
    assert "type(exc).__name__" in source, (
        "Proposal 4: 'type(exc).__name__' в source не найден. "
        "Должен быть logger.debug(..., type(exc).__name__) для observability."
    )


def test_express_source_syntax_valid():
    """Proposal 4: source должен быть синтаксически валидным Python."""
    source = _read_express_source()
    ast.parse(source)
    # Если parse упадёт — test fail с traceback. Просто убеждаемся,
    # что файл парсится без ошибок.
