"""Tests for core.audit.sinks.ai_unified_sink.UnifiedAISink.

Layer 2 (Core Kernel) coverage: audit sink that dual-writes AI invocation
events to ClickHouse + Langfuse. Cycle 41 review identified this file as
having zero direct test coverage — security-relevant (audit-trail risk).

Tests focus on:
- emit_event no-op when disabled (default)
- emit_event writes to ClickHouse + Langfuse when enabled
- Fail-closed semantics: drops event on PII tokenizer init failure
- Fail-closed semantics: drops event on PII mask failure
- emit_sequence iterates events
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.audit.sinks.ai_unified_sink import UnifiedAISink


def _event_type(name: str = "INVOCATION_START") -> MagicMock:
    """Build a mock AIInvocationEventType (string-based enum)."""
    return MagicMock(name=name, value=name)


def _event(
    *,
    error_message: str | None = None,
    event_type_name: str = "INVOCATION_START",
) -> MagicMock:
    """Build a mock AIInvocationEvent."""
    event = MagicMock()
    event.error_message = error_message
    event.event_type = _event_type(event_type_name)
    return event


class TestUnifiedAISinkDisabled:
    """Sink is no-op when disabled (default state)."""

    @pytest.mark.asyncio
    async def test_emit_event_is_noop_when_disabled(self) -> None:
        """enabled=False (default): emit_event returns immediately.

        Neither ClickHouse nor Langfuse are touched (defense: avoids
        dependency on sinks during tests / dev_light).
        """
        audit = AsyncMock()
        langfuse = AsyncMock()
        sink = UnifiedAISink(
            audit_service=audit, langfuse_callback=langfuse, enabled=False
        )
        await sink.emit_event(_event())

        audit.emit.assert_not_called()
        langfuse.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_emit_sequence_is_noop_when_disabled(self) -> None:
        sink = UnifiedAISink(enabled=False)
        await sink.emit_sequence([_event(), _event()])


class TestUnifiedAISinkEnabled:
    """Sink writes to ClickHouse when enabled."""

    @pytest.mark.asyncio
    async def test_emit_event_calls_clickhouse_when_enabled(self) -> None:
        """enabled=True: emit_event writes to ClickHouse via audit backend."""
        audit = AsyncMock()
        sink = UnifiedAISink(audit_service=audit, enabled=True)

        import sys

        mock_pii_instance = MagicMock()
        mock_pii_instance.mask_irreversible = MagicMock(side_effect=lambda x: x)
        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer = MagicMock(return_value=mock_pii_instance)

        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_event(_event())

        audit.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_event_calls_langfuse_when_callback_provided(self) -> None:
        """enabled=True + langfuse_callback (with _generation_id): also flushes."""
        audit = AsyncMock()
        langfuse = MagicMock()
        langfuse._generation_id = "gen-123"
        langfuse.flush = MagicMock()
        sink = UnifiedAISink(
            audit_service=audit, langfuse_callback=langfuse, enabled=True
        )

        import sys

        mock_pii_instance = MagicMock()
        mock_pii_instance.mask_irreversible = MagicMock(side_effect=lambda x: x)
        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer = MagicMock(return_value=mock_pii_instance)

        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_event(_event())

        audit.emit.assert_awaited_once()
        # Langfuse flush is sync (no await).
        langfuse.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_langfuse_skipped_when_no_generation_id(self) -> None:
        """langfuse without _generation_id → flush skipped (early return)."""
        audit = AsyncMock()
        langfuse = MagicMock()
        if hasattr(langfuse, "_generation_id"):
            del langfuse._generation_id
        langfuse.flush = MagicMock()
        sink = UnifiedAISink(
            audit_service=audit, langfuse_callback=langfuse, enabled=True
        )

        import sys

        mock_pii_instance = MagicMock()
        mock_pii_instance.mask_irreversible = MagicMock(side_effect=lambda x: x)
        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer = MagicMock(return_value=mock_pii_instance)

        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_event(_event())

        audit.emit.assert_awaited_once()
        langfuse.flush.assert_not_called()


class TestUnifiedAISinkFailClosed:
    """Sink drops events on PII failures (defense-in-depth)."""

    @pytest.mark.asyncio
    async def test_pii_tokenizer_init_failure_drops_event(self) -> None:
        """PIITokenizer fails to initialize → event dropped, no write.

        Critical: prevents PII from leaking to audit storage when tokenization
        pipeline is broken. Fail-closed (NOT fail-open) — event loss is
        preferable to PII leak.

        Note: PIITokenizer is lazy-imported inside _emit_clickhouse, so
        we patch the SOURCE module path (security.pii_tokenizer.PIITokenizer)
        not the consumer module attribute.
        """
        audit = AsyncMock()
        sink = UnifiedAISink(audit_service=audit, enabled=True)

        # Patch PIITokenizer at its source so lazy import resolves to mock.
        import sys

        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer.side_effect = ImportError(
            "tokenizer broken"
        )
        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_event(_event())

        audit.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_pii_mask_failure_drops_event(self) -> None:
        """PIITokenizer.mask_irreversible raises → event dropped (fail-closed)."""
        audit = AsyncMock()
        sink = UnifiedAISink(audit_service=audit, enabled=True)

        import sys

        mock_pii_instance = MagicMock()
        mock_pii_instance.mask_irreversible = MagicMock(
            side_effect=RuntimeError("mask failed")
        )

        # Mock the class instantiation to return our configured instance.
        mock_pii_class = MagicMock(return_value=mock_pii_instance)
        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer = mock_pii_class

        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_event(_event(error_message="user@example.com"))

        audit.emit.assert_not_called()


class TestUnifiedAISinkSequence:
    """emit_sequence iterates events in order."""

    @pytest.mark.asyncio
    async def test_emit_sequence_iterates_all_events(self) -> None:
        """emit_sequence calls emit_event for each input event."""
        audit = AsyncMock()
        sink = UnifiedAISink(audit_service=audit, enabled=True)

        events = [_event(), _event(), _event()]

        import sys

        mock_pii_instance = MagicMock()
        mock_pii_instance.mask_irreversible = MagicMock(side_effect=lambda x: x)
        mock_pii_module = MagicMock()
        mock_pii_module.PIITokenizer = MagicMock(return_value=mock_pii_instance)

        with patch.dict(
            sys.modules,
            {"src.backend.core.security.pii_tokenizer": mock_pii_module},
        ):
            await sink.emit_sequence(events)

        assert audit.emit.await_count == 3

    @pytest.mark.asyncio
    async def test_emit_sequence_empty_list_is_noop(self) -> None:
        audit = AsyncMock()
        sink = UnifiedAISink(audit_service=audit, enabled=True)
        await sink.emit_sequence([])
        audit.emit.assert_not_called()
