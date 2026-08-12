"""Unit-тесты core/observability/correlation.py (cycle 33 L2 cycle 1).

Этот модуль — pure stdlib (contextvars + structlog) — фундамент для
correlation_id/request_id/tenant_id propagation через async-задачи.
Используется всеми log-events и audit-events; ошибка в нём =
невозможность корреляции трейсов между сервисами.

Существующие тесты (test_correlation_propagation.py) проверяют
ИСПОЛЬЗОВАНИЕ модуля из outbox — но не primitives напрямую. Без
прямых тестов контракт модуля (set/get/new) не покрыт.
"""


from __future__ import annotations

import pytest
import structlog

from src.backend.core.observability.correlation import (
    correlation_id_var,
    get_correlation_id,
    get_request_id,
    get_tenant_id,
    new_correlation_id,
    request_id_var,
    set_correlation_context,
    tenant_id_var,
)


@pytest.fixture(autouse=True)
def _reset_context_state() -> None:
    """Reset all 3 ContextVars + structlog context до/после каждого теста.

    ContextVar.set() на main scope persist'ит между тестами в pytest
    (default scope = function для module-scope vars). Без reset —
    test order зависимости: ``test_set_correlation_context_sets_all_three``
    устанавливает tenant_id, и ``test_set_correlation_context_partial_args``
    видит leaked value.
    """
    correlation_id_var.set("")
    request_id_var.set("")
    tenant_id_var.set("")
    structlog.contextvars.clear_contextvars()
    yield
    correlation_id_var.set("")
    request_id_var.set("")
    tenant_id_var.set("")
    structlog.contextvars.clear_contextvars()


def test_context_vars_default_to_empty_string() -> None:
    """Default values всех 3 ContextVar — пустая строка, не None."""
    assert correlation_id_var.get() == ""
    assert request_id_var.get() == ""
    assert tenant_id_var.get() == ""


def test_get_correlation_id_returns_current_value() -> None:
    """get_* возвращают текущее значение ContextVar."""
    correlation_id_var.set("test-cid-123")
    request_id_var.set("test-rid-456")
    tenant_id_var.set("test-tenant-789")

    assert get_correlation_id() == "test-cid-123"
    assert get_request_id() == "test-rid-456"
    assert get_tenant_id() == "test-tenant-789"

    # Cleanup.
    correlation_id_var.set("")
    request_id_var.set("")
    tenant_id_var.set("")


def test_set_correlation_context_sets_all_three() -> None:
    """set_correlation_context с всеми 3 args — устанавливает все 3 vars."""
    set_correlation_context(
        correlation_id="ctx-cid",
        request_id="ctx-rid",
        tenant_id="ctx-tenant",
    )
    assert get_correlation_id() == "ctx-cid"
    assert get_request_id() == "ctx-rid"
    assert get_tenant_id() == "ctx-tenant"


def test_set_correlation_context_partial_args() -> None:
    """Partial set (только correlation_id) — НЕ трогает остальные vars."""
    set_correlation_context(correlation_id="only-cid", request_id="keep-rid")
    assert get_correlation_id() == "only-cid"
    assert get_request_id() == "keep-rid"
    assert get_tenant_id() == ""  # default


def test_set_correlation_context_none_args_skipped() -> None:
    """None args — skipped, не overwrites существующие значения."""
    set_correlation_context(
        correlation_id="initial-cid", request_id="initial-rid", tenant_id="initial-tenant",
    )
    set_correlation_context(correlation_id=None, request_id=None, tenant_id=None)
    # Существующие значения сохранены (None не overwrites).
    assert get_correlation_id() == "initial-cid"
    assert get_request_id() == "initial-rid"
    assert get_tenant_id() == "initial-tenant"


@pytest.mark.unit
def test_set_correlation_context_empty_correlation_id_clears_existing_value() -> None:
    """Пустой correlation_id затирает предыдущее значение во всех контекстах."""
    set_correlation_context(correlation_id="existing-cid")

    set_correlation_context(correlation_id="")

    assert get_correlation_id() == ""
    assert structlog.contextvars.get_contextvars()["correlation_id"] == ""


def test_set_correlation_context_binds_to_structlog() -> None:
    """set_correlation_context зеркалит values в structlog contextvars.

    R-V15-11: values попадают в каждое log-event через
    structlog.contextvars, без явного logger.bind.
    """
    set_correlation_context(
        correlation_id="log-cid",
        request_id="log-rid",
        tenant_id="log-tenant",
    )
    # structlog хранит context в contextvars.copy_context();
    # bound values доступны через structlog.contextvars.get_contextvars().
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("correlation_id") == "log-cid"
    assert ctx.get("request_id") == "log-rid"
    assert ctx.get("tenant_id") == "log-tenant"


def test_set_correlation_context_empty_args_does_not_bind() -> None:
    """Все args None/empty — НЕ дёргает structlog.bind_contextvars (no-op)."""
    # Сначала clear structlog context.
    structlog.contextvars.clear_contextvars()
    set_correlation_context()
    ctx = structlog.contextvars.get_contextvars()
    # Пустой dict — bind не вызывался.
    assert ctx == {}


def test_new_correlation_id_generates_unique_value() -> None:
    """new_correlation_id() возвращает уникальный ID и устанавливает в var."""
    cid1 = new_correlation_id()
    cid2 = new_correlation_id()

    # Возвращённый ID — 16-символьный hex (uuid4.hex[:16]).
    assert len(cid1) == 16
    assert len(cid2) == 16
    assert cid1 != cid2  # unique

    # Последний вызов set'ит var (не возвращённое значение).
    assert get_correlation_id() == cid2


def test_new_correlation_id_format_is_hex() -> None:
    """new_correlation_id() — UUID4 hex (lowercase a-f0-9)."""
    cid = new_correlation_id()
    assert all(c in "0123456789abcdef" for c in cid), (
        f"correlation_id {cid!r} содержит не-hex символы"
    )


def test_context_vars_isolated_between_async_tasks() -> None:
    """ContextVars propagation: asyncio.run creates fresh context.

    Внутри одного ``asyncio.run()`` — child tasks НАСЛЕДУЮТ parent
    context (asyncio.create_task snapshots current context). Реальная
    isolation происходит между разными ``asyncio.run()`` invocations
    (разные event loops, разные main tasks).

    Это важный контракт: middleware, который set context в request
    scope, может безопасно использовать ContextVars в async-цепочке
    (handler → downstream call → response), и parent context НЕ
    «протекает» в другие requests благодаря ``asyncio.run()`` isolation.
    """
    import asyncio

    set_correlation_context(correlation_id="outer-cid")

    async def inner_task() -> str:
        # Child task видит parent context (asyncio inheritance).
        return get_correlation_id()

    async def inner_with_override() -> str:
        # Child task может override — НЕ мутирует parent.
        set_correlation_context(correlation_id="inner-cid")
        return get_correlation_id()

    async def main() -> tuple[str, str]:
        c1 = await inner_task()
        c2 = await inner_with_override()
        return c1, c2

    c1, c2 = asyncio.run(main())

    # Child НАСЛЕДУЕТ parent context (asyncio contract).
    assert c1 == "outer-cid"
    # Override в child — возвращает overridden value.
    assert c2 == "inner-cid"
    # Parent scope сохранён (override в child не мутирует).
    assert get_correlation_id() == "outer-cid"
