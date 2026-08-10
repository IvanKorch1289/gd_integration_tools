"""Regression tests: ``PiiEraseProcessor`` теперь fail-CLOSED при сбое
backend erasure (cycle-8/D-AUDIT-804).

Раньше ``_delete_vectors`` / ``_anonymize_db`` под bare ``except Exception``
молча возвращали ``0`` — PII оставался в vector store / таблице
``<entity>_pii`` (ADR-152FZ regression). Теперь:

* Inner methods логируют ``_logger.error`` и ``raise`` до outer ``process()``;
* Outer ``process()`` enqueue DLQ (``InMemoryDLQWriter``) + ``raise``;
* ``@handle_processor_error`` decorator помечает exchange как failed.

Эти тесты верифицируют fail-CLOSED contract:
mock exception в backend → ``process()`` re-raises → exchange failed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange


def _load_pii_erase_module() -> Any:
    """Load ``pii_erase`` module через importlib (security.py namespace shadow)."""
    src = (
        Path(__file__).resolve().parents[4]
        / "src/backend/dsl/engine/processors/security/pii_erase.py"
    )
    module_name = "_gd_pii_erase_failclosed_under_test"
    spec = importlib.util.spec_from_file_location(module_name, src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_exchange() -> Exchange[Any]:
    """Создать fresh Exchange для каждого теста."""
    return Exchange(body={}, headers={})


def _make_context() -> ExecutionContext:
    """Создать stub ExecutionContext (capability facade мокается отдельно)."""
    ctx = MagicMock(spec=ExecutionContext)
    ctx.tenant_id = "test-tenant"
    return ctx


def _cap_facade_mock(*, allow: bool) -> Any:
    """Mock capability facade — все capabilities разрешены или отклонены."""
    facade = MagicMock()
    facade.check = MagicMock(return_value=allow)
    return facade


class TestDeleteVectorsFailClosed:
    """``_delete_vectors`` failure → ``process()`` re-raises (fail-CLOSED)."""

    @pytest.mark.asyncio
    async def test_vector_backend_failure_raises_not_silent(self) -> None:
        """Mock exception в vector store backend → ``_delete_vectors``
        propagate до outer ``process()``, который re-raises (НЕ silent
        return 0). Это — фикс fail-OPEN (cycle-8/D-AUDIT-804).
        """
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)

        # Patch vector store to raise
        fake_store = MagicMock()
        fake_store.delete_where = AsyncMock(
            side_effect=ConnectionError("qdrant backend unreachable"),
        )

        with patch(
            "src.backend.infrastructure.clients.storage.vector_store.get_vector_store",
            return_value=fake_store,
        ), patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
            return_value=_cap_facade_mock(allow=True),
        ):
            # Inner _delete_vectors should raise (not return 0 silently).
            with pytest.raises(ConnectionError, match="qdrant backend"):
                await proc._delete_vectors("erasure-1")

    @pytest.mark.asyncio
    async def test_process_vector_failure_marks_exchange_failed(self) -> None:
        """Full ``process()`` flow: vector backend down → exception
        propagates через ``@handle_processor_error`` → exchange.error
        установлен + exchange.stopped = True (НЕ silent success)."""
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)
        exchange = _make_exchange()
        context = _make_context()

        fake_store = MagicMock()
        fake_store.delete_where = AsyncMock(
            side_effect=ConnectionError("qdrant backend unreachable"),
        )

        with patch(
            "src.backend.infrastructure.clients.storage.vector_store.get_vector_store",
            return_value=fake_store,
        ), patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
            return_value=_cap_facade_mock(allow=True),
        ):
            # @handle_processor_error catches re-raise → exchange.error + stop.
            await proc.process(exchange, context)
        assert exchange.stopped is True, (
            "exchange должен быть остановлен при vector backend error "
            "(fail-CLOSED contract, ADR-152FZ)"
        )
        assert exchange.error is not None, (
            "exchange.error должен быть установлен при vector backend error"
        )
        assert "qdrant backend" in exchange.error


class TestAnonymizeDbFailClosed:
    """``_anonymize_db`` failure → ``process()`` re-raises (fail-CLOSED)."""

    @pytest.mark.asyncio
    async def test_db_backend_failure_raises_not_silent(self) -> None:
        """Mock exception в DB backend → ``_anonymize_db`` propagate
        (НЕ silent return 0)."""
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)

        # Build fake session manager whose get_session raises on context-manager enter.
        class _RaisingCtx:
            async def __aenter__(self) -> Any:
                raise ConnectionError("postgres unreachable")

            async def __aexit__(self, *a: Any) -> bool:
                return False

        fake_mgr = MagicMock()
        fake_mgr.get_session = MagicMock(return_value=_RaisingCtx())
        with patch(
            "src.backend.infrastructure.database.session_manager.main_session_manager",
            fake_mgr,
        ):
            with pytest.raises(ConnectionError, match="postgres unreachable"):
                await proc._anonymize_db("erasure-1")

    @pytest.mark.asyncio
    async def test_process_db_failure_marks_exchange_failed(self) -> None:
        """Full ``process()`` flow: DB backend down → exchange failed."""
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)
        exchange = _make_exchange()
        context = _make_context()

        class _RaisingCtx:
            async def __aenter__(self) -> Any:
                raise ConnectionError("postgres unreachable")

            async def __aexit__(self, *a: Any) -> bool:
                return False

        fake_mgr = MagicMock()
        fake_mgr.get_session = MagicMock(return_value=_RaisingCtx())
        with patch(
            "src.backend.infrastructure.database.session_manager.main_session_manager",
            fake_mgr,
        ), patch(
            "src.backend.services.capabilities.facade.get_capability_facade",
            return_value=_cap_facade_mock(allow=True),
        ):
            # Stub vector store чтобы vector step прошёл успешно.
            fake_store = MagicMock()
            fake_store.delete_where = AsyncMock(return_value=0)
            with patch(
                "src.backend.infrastructure.clients.storage.vector_store.get_vector_store",
                return_value=fake_store,
            ):
                await proc.process(exchange, context)
        assert exchange.stopped is True, (
            "exchange должен быть остановлен при DB backend error (fail-CLOSED)"
        )
        assert exchange.error is not None, (
            "exchange.error должен быть установлен при DB backend error"
        )
        assert "postgres unreachable" in exchange.error


class TestDqWriteEnqueue:
    """``_enqueue_failure_to_dlq`` корректно строит ``DLQEnvelope`` и пишет."""

    @pytest.mark.asyncio
    async def test_enqueue_writes_envelope_to_dlq(self) -> None:
        """Failure path → ``InMemoryDLQWriter`` получает envelope с
        erasure_id / step / error_class."""
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)


        captured: list[Any] = []

        class _CaptureWriter:
            def __init__(self) -> None:
                self.records: list[Any] = []

            async def write(self, envelope: Any) -> None:
                self.records.append(envelope)
                captured.append(envelope)

        with patch(
            "src.backend.infrastructure.messaging.dlq.memory_writer.InMemoryDLQWriter",
            _CaptureWriter,
        ):
            exc = ConnectionError("backend down")
            await proc._enqueue_failure_to_dlq(
                erasure_id="erasure-abc",
                step="vectors",
                exc=exc,
            )
        assert len(captured) == 1
        env = captured[0]
        assert env.transport == "dsl.pii_erase"
        assert env.route_id == "pii_erase[user:42]"
        assert env.original_payload == {"erasure_id": "erasure-abc", "step": "vectors"}
        assert env.error_class == "ConnectionError"
        assert "backend down" in env.error_message

    @pytest.mark.asyncio
    async def test_enqueue_swallows_dlq_own_failure(self) -> None:
        """DLQ сам недоступен → log error, НО не raise
        (outer process() уже re-raise основную ошибку)."""
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)

        # Force DLQEnvelope construction to fail.
        with patch(
            "src.backend.core.di.providers.dlq_bridge.get_dlq_envelope_class",
            side_effect=RuntimeError("dlq bridge unavailable"),
        ):
            # Should NOT raise — DLQ self-failure is logged + swallowed.
            await proc._enqueue_failure_to_dlq(
                erasure_id="erasure-xyz",
                step="db_anonymize",
                exc=ValueError("primary failure"),
            )
