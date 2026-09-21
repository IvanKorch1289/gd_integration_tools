"""S66 W4: verification test для BatchUpdateProcessor executemany behavior.

Анализ P1-5 (comprehensive audit) утверждал:
> "BatchUpdateProcessor — один UPDATE per item (цикл)"
> "for item in batch: await session.execute(update_stmt, item)"

S66 W4 fact-check: код РЕАЛЬНО делает ``executemany`` per column-group,
а не цикл per item. Этот тест ЗАКРЕПЛЯЕТ текущее (правильное) поведение.

Если кто-то "оптимизирует" код до cycle-per-item — этот тест
должен сломаться.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.batch import BatchUpdateProcessor


@pytest.mark.asyncio
async def test_batch_update_uses_executemany_not_cycle() -> None:
    """BatchUpdateProcessor.process должен вызывать session.execute
    с params_list (executemany), а не в цикле.

    Проверяем:
    1. ``session.execute`` вызывается для каждого UNIQUE column-group
       (а не per item);
    2. Каждый вызов получает LIST of params (executemany signature),
       а не одиночный dict;
    3. Если в items все с одинаковыми columns → ровно 1 execute call.
    """
    # Items: все обновляют одинаковые колонки (col_a, col_b) → 1 group
    items = [
        {"id": 1, "col_a": "x1", "col_b": "y1"},
        {"id": 2, "col_a": "x2", "col_b": "y2"},
        {"id": 3, "col_a": "x3", "col_b": "y3"},
    ]

    # Mock session
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    execute_result = MagicMock()
    execute_result.rowcount = 3
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()

    # Mock bundle
    bundle = MagicMock()
    bundle.async_session_maker = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    # Mock registry
    registry = MagicMock()
    registry.get_bundle = MagicMock(return_value=bundle)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry",
            lambda: lambda: registry,
        )

        processor = BatchUpdateProcessor(table="users", items=items, key_field="id")
        exchange = MagicMock()
        exchange.in_message.body = items
        exchange.in_message.headers = {}
        exchange.set_property = MagicMock()
        exchange.set_out = MagicMock()
        context = MagicMock()

        await processor.process(exchange, context)

    # CRITICAL assertion: executemany, не cycle.
    # Если бы был цикл per item — было бы 3 вызова (по items).
    # executemany: 1 вызов (все 3 items в один params_list).
    assert session.execute.await_count == 1, (
        f"Expected 1 executemany call (1 column-group), got "
        f"{session.execute.await_count} — это значит код = cycle per item "
        f"(анти-паттерн, см. analysis P1-5)."
    )

    # Verify params passed as LIST (executemany signature)
    call = session.execute.await_args
    # text(stmt) — positional arg 0; params — positional arg 1
    params_arg = call.args[1] if len(call.args) > 1 else call.kwargs.get("params")
    assert isinstance(params_arg, list), (
        f"Expected params as list (executemany), got {type(params_arg).__name__}"
    )
    assert len(params_arg) == 3  # 3 items в одном executemany call


def test_batch_update_docstring_does_not_claim_cycle() -> None:
    """Docstring не должен говорить 'cycle per item' или 'one per item'."""
    src = inspect.getsource(BatchUpdateProcessor)
    # Старый вводящий в заблуждение docstring был "один statement на item"
    assert "один statement на item" not in src, (
        "Docstring по-прежнему вводит в заблуждение ('один statement на item'). "
        "S66 W4 исправил на 'executemany per column-group'."
    )
    # Правильный паттерн должен быть упомянут
    assert "executemany" in src.lower(), (
        "Docstring должен явно упоминать executemany pattern"
    )


def test_batch_update_process_method_uses_executemany_pattern() -> None:
    """Static check: process() использует session.execute(text(stmt), params_list).

    Не cycle вида:
        for item in items:
            await session.execute(update_stmt, item)
    """
    src = inspect.getsource(BatchUpdateProcessor.process)
    # executemany signature: session.execute(text(stmt), params_list)
    assert "session.execute" in src
    # Должен быть call с list (params_list)
    assert "params_list" in src, (
        "process() должен передавать params_list в session.execute (executemany), "
        "а не отдельный item в цикле."
    )
