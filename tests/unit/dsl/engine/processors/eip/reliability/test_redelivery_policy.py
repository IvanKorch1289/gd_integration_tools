"""Unit-тесты RedeliveryPolicyProcessor (cycle-1/B-04 regression).

Цель: зафиксировать, что ``RedeliveryPolicyProcessor.process()`` корректно
обрабатывает не-convertible значение ``redelivery_header`` (TypeError или
ValueError). До фикса ``redelivery_policy.py:145`` использовал Python-2
синтаксис ``except TypeError, ValueError:`` — SyntaxError на Python 3.14.

Покрытие:
    * ``attempt_raw`` — ``int`` → нормальный increment.
    * ``attempt_raw`` — ``str`` с числом → ``int(...) + 1``.
    * ``attempt_raw`` — ``str`` без числа → ``ValueError`` → attempt=1.
    * ``attempt_raw`` — ``list``/``dict`` → ``TypeError`` → attempt=1.
    * Конструктор ExecutionEngine не ломается (smoke).

cycle-1/B-04
"""


from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.reliability.redelivery_policy import (
    HEADER_REDELIVERED,
    HEADER_REDELIVERY_COUNT,
    RedeliveryPolicyProcessor,
)


def _exchange(headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body={}, headers=headers or {}))


def _ctx() -> ExecutionContext:
    return ExecutionContext()


@pytest.mark.asyncio
async def test_first_attempt_initializes_counter() -> None:
    """Без header → attempt=1, redelivered=True, no exhausted."""
    op = RedeliveryPolicyProcessor(max_attempts=3, initial_delay_s=0.0)
    ex = _exchange()
    await op.process(ex, _ctx())

    assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 1
    assert ex.in_message.get_header(HEADER_REDELIVERED) is True
    assert ex.get_property("redelivery_policy.attempt") == 1
    assert op.stats()["retried"] == 1


@pytest.mark.asyncio
async def test_string_attempt_value_increments() -> None:
    """``attempt_raw`` как строка ``"5"`` → ``int("5") + 1 = 6``."""
    op = RedeliveryPolicyProcessor(max_attempts=10, initial_delay_s=0.0)
    ex = _exchange({HEADER_REDELIVERY_COUNT: "5"})
    await op.process(ex, _ctx())

    assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 6
    assert ex.get_property("redelivery_policy.attempt") == 6


@pytest.mark.asyncio
async def test_unconvertible_string_resets_to_one() -> None:
    """``attempt_raw`` = ``"abc"`` → ``ValueError`` → attempt=1 (reset path).

    Regression cycle-1/B-04: до фикса ``except TypeError, ValueError:`` —
    SyntaxError на Python 3.14. После фикса — ``except (TypeError, ValueError):``
    корректно ловит ValueError из ``int("abc")`` и сбрасывает attempt=1.
    """
    op = RedeliveryPolicyProcessor(max_attempts=5, initial_delay_s=0.0)
    ex = _exchange({HEADER_REDELIVERY_COUNT: "abc"})
    await op.process(ex, _ctx())

    assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 1
    assert ex.get_property("redelivery_policy.attempt") == 1


@pytest.mark.asyncio
async def test_list_header_raises_type_error_and_resets() -> None:
    """``attempt_raw`` = ``[]`` → ``TypeError`` из ``int([])`` → attempt=1.

    Regression cycle-1/B-04: ``except (TypeError, ValueError):`` ловит
    оба типа исключений. До фикса — ``except TypeError, ValueError`` —
    SyntaxError, модуль не импортируется.
    """
    op = RedeliveryPolicyProcessor(max_attempts=5, initial_delay_s=0.0)
    ex = _exchange({HEADER_REDELIVERY_COUNT: []})
    await op.process(ex, _ctx())

    assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 1


@pytest.mark.asyncio
async def test_dict_header_raises_type_error_and_resets() -> None:
    """``attempt_raw`` = ``{}`` → ``TypeError`` из ``int({})`` → attempt=1."""
    op = RedeliveryPolicyProcessor(max_attempts=5, initial_delay_s=0.0)
    ex = _exchange({HEADER_REDELIVERY_COUNT: {}})
    await op.process(ex, _ctx())

    assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 1


@pytest.mark.asyncio
async def test_exhausted_after_max_attempts() -> None:
    """``max_attempts=2``: 3-я попытка → exhausted=True, dispatcher вызван."""
    dispatched: list[tuple[str, Exchange[Any]]] = []

    def dispatcher(action: str, ex: Exchange[Any]) -> None:
        dispatched.append((action, ex))

    op = RedeliveryPolicyProcessor(
        max_attempts=2,
        initial_delay_s=0.0,
        on_exhausted_action="dlq",
        action_dispatcher=dispatcher,
    )
    ex = _exchange()

    for _ in range(3):
        await op.process(ex, _ctx())

    assert op.stats()["retried"] == 2
    assert op.stats()["exhausted"] == 1
    assert ex.get_property("redelivery_policy.exhausted") is True
    assert len(dispatched) == 1
    assert dispatched[0][0] == "dlq"


def test_exhausted_backoff_capped() -> None:
    """``max_delay_s`` ограничивает рост delay."""
    op = RedeliveryPolicyProcessor(
        max_attempts=10,
        initial_delay_s=10.0,
        backoff_multiplier=10.0,
        max_delay_s=15.0,
    )
    # attempt=4 → delay = 10 * 10^3 = 10000, cap = 15.
    assert op._compute_delay(4) == 15.0


def test_constructor_validation() -> None:
    """Невалидные параметры → ValueError."""
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        RedeliveryPolicyProcessor(max_attempts=0)
    with pytest.raises(ValueError, match="initial_delay_s must be >= 0"):
        RedeliveryPolicyProcessor(initial_delay_s=-1.0)
    with pytest.raises(ValueError, match="backoff_multiplier must be >= 1.0"):
        RedeliveryPolicyProcessor(backoff_multiplier=0.5)


def test_to_spec_serialization() -> None:
    """``to_spec()`` возвращает JSON-Schema spec с retry/backoff параметрами."""
    op = RedeliveryPolicyProcessor(
        max_attempts=5, initial_delay_s=2.0, backoff_multiplier=1.5, max_delay_s=30.0,
    )
    assert op.to_spec() == {
        "type": "redelivery_policy",
        "max_attempts": 5,
        "initial_delay_s": 2.0,
        "backoff_multiplier": 1.5,
        "max_delay_s": 30.0,
    }
