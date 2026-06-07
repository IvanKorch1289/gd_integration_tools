"""Sprint 60 W1 — compat shim tests for StructlogLogger.

Покрывает обратную совместимость со stdlib-style API:
- ``logger.warning("msg %s", arg)`` (positional %-formatting)
- ``logger.info("msg", key=val)`` (structlog kwargs)
- ``logger.exception("msg", exc_info=True)`` (auto-inject exc_info)

Это фикс S59 W2 lesson — ранее default-switch structlog ломал callers
из-за несовместимости API. Теперь compat shim в ``StructlogLogger._format``
перехватывает ``*args`` и применяет ``%``-форматирование ДО передачи в structlog.
"""

# ruff: noqa: S101, D103, ANN001, ANN201

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.logging.structlog_backend import StructlogLogger


class _RecorderInner:
    """Mock structlog.BoundLogger — записывает все вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def debug(self, msg: str, **kw: Any) -> None:
        self.calls.append(("debug", msg, kw))

    def info(self, msg: str, **kw: Any) -> None:
        self.calls.append(("info", msg, kw))

    def warning(self, msg: str, **kw: Any) -> None:
        self.calls.append(("warning", msg, kw))

    def error(self, msg: str, **kw: Any) -> None:
        self.calls.append(("error", msg, kw))

    def exception(self, msg: str, **kw: Any) -> None:
        self.calls.append(("exception", msg, kw))

    def bind(self, **kw: Any) -> "_RecorderInner":
        return self  # bind не тестируется в compat shim


def _new_logger() -> tuple[StructlogLogger, _RecorderInner]:
    inner = _RecorderInner()
    return StructlogLogger(inner), inner


# ---------------------------------------------------------------------- %-formatting


def test_info_with_single_positional_arg() -> None:
    sl, inner = _new_logger()
    sl.info("Hello %s", "world")
    assert inner.calls == [("info", "Hello world", {})]


def test_warning_with_two_positional_args() -> None:
    sl, inner = _new_logger()
    sl.warning("User %s not %s", "alice", "found")
    assert inner.calls == [("warning", "User alice not found", {})]


def test_error_with_int_format() -> None:
    sl, inner = _new_logger()
    sl.error("Retries: %d / %d", 3, 5)
    assert inner.calls == [("error", "Retries: 3 / 5", {})]


def test_debug_with_float_format() -> None:
    sl, inner = _new_logger()
    sl.debug("Memory: %.2f MB", 123.456)
    assert inner.calls == [("debug", "Memory: 123.46 MB", {})]


def test_mixed_positional_and_kwargs() -> None:
    sl, inner = _new_logger()
    sl.info("Order %s created", "ORD-1", user_id="u-42")
    assert inner.calls == [("info", "Order ORD-1 created", {"user_id": "u-42"})]


def test_no_args_passes_through() -> None:
    sl, inner = _new_logger()
    sl.info("plain message")
    assert inner.calls == [("info", "plain message", {})]


def test_kwarg_only_passes_through() -> None:
    sl, inner = _new_logger()
    sl.info("Order created", order_id=123, tenant_id="t-1")
    assert inner.calls == [("info", "Order created", {"order_id": 123, "tenant_id": "t-1"})]


# ---------------------------------------------------------------------- exception


def test_exception_auto_injects_exc_info() -> None:
    sl, inner = _new_logger()
    sl.exception("Boom: %s", "kafka")
    assert inner.calls == [("exception", "Boom: kafka", {"exc_info": True})]


def test_exception_explicit_exc_info_overrides() -> None:
    """explicit exc_info=False переопределяет default (auto True)."""
    sl, inner = _new_logger()
    sl.exception("custom", exc_info=False)
    # setdefault НЕ перезаписывает, если ключ уже есть с truthy значением
    # но exc_info=False устанавливается ДО setdefault
    assert inner.calls == [("exception", "custom", {"exc_info": False})]


def test_exception_with_extra_kwargs() -> None:
    sl, inner = _new_logger()
    sl.exception("Redis %s down", "node-3", host="redis-1", port=6379)
    assert inner.calls == [
        ("exception", "Redis node-3 down", {"host": "redis-1", "port": 6379, "exc_info": True})
    ]


# ---------------------------------------------------------------------- % failures


def test_unparseable_format_passes_args_as_kwarg() -> None:
    """Если %-formatting падает (нет %-placeholders), args → kwargs['args']."""
    sl, inner = _new_logger()
    sl.warning("plain text with extra", "arg1", "arg2")
    # msg не имеет %-placeholders → TypeError → args записываются в kwargs
    assert inner.calls == [("warning", "plain text with extra", {"args": ["arg1", "arg2"]})]


def test_typing_format_passes_through() -> None:
    """`%s` с non-string args через str() coercion."""
    sl, inner = _new_logger()
    sl.info("Counter: %s", 42)  # int coerced to "42" by %s
    assert inner.calls == [("info", "Counter: 42", {})]


# ---------------------------------------------------------------------- bind() compat


def test_bind_returns_new_structlog_logger() -> None:
    sl, _ = _new_logger()
    bound = sl.bind(tenant_id="t-1")
    assert isinstance(bound, StructlogLogger)
    assert bound is not sl


def test_bind_preserves_inner() -> None:
    sl, inner = _new_logger()
    bound = sl.bind(context="x")
    assert bound._inner is inner  # наш mock bind() возвращает self


# ---------------------------------------------------------------------- stress


def test_100_logs_no_state_leak() -> None:
    """100 последовательных логов — каждая запись изолирована, нет state leak."""
    sl, inner = _new_logger()
    for i in range(100):
        sl.info("log %s with %s", i, "arg")
    assert len(inner.calls) == 100
    for idx, (level, msg, kw) in enumerate(inner.calls):
        assert level == "info"
        assert msg == f"log {idx} with arg"
        assert kw == {}


def test_unicode_in_args() -> None:
    sl, inner = _new_logger()
    sl.info("User %s logged in from %s", "Иван", "Москва")
    assert inner.calls == [("info", "User Иван logged in from Москва", {})]


def test_none_in_args() -> None:
    sl, inner = _new_logger()
    sl.info("Value: %s", None)
    assert inner.calls == [("info", "Value: None", {})]


def test_empty_string_in_args() -> None:
    sl, inner = _new_logger()
    sl.info("Prefix: [%s]", "")
    assert inner.calls == [("info", "Prefix: []", {})]


def test_dict_in_args_uses_str() -> None:
    sl, inner = _new_logger()
    sl.info("Data: %s", {"k": "v"})
    assert inner.calls == [("info", "Data: {'k': 'v'}", {})]


# ---------------------------------------------------------------------- methods parity


def test_all_levels_support_positional_args() -> None:
    sl, inner = _new_logger()
    sl.debug("d %s", 1)
    sl.info("i %s", 2)
    sl.warning("w %s", 3)
    sl.error("e %s", 4)
    sl.exception("x %s", 5)
    assert [c[0] for c in inner.calls] == ["debug", "info", "warning", "error", "exception"]
    assert [c[1] for c in inner.calls] == ["d 1", "i 2", "w 3", "e 4", "x 5"]


def test_format_helper_is_static() -> None:
    """_format не требует self, может быть вызван как static method."""
    msg, kw = StructlogLogger._format("hello %s", ("world",), {"x": 1})
    assert msg == "hello world"
    assert kw == {"x": 1}


def test_format_helper_empty_args() -> None:
    """_format с пустыми args возвращает msg без изменений."""
    msg, kw = StructlogLogger._format("plain", (), {})
    assert msg == "plain"
    assert kw == {}
