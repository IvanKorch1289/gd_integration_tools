"""Coverage tests для handle_mixin (Sprint 223, 2026-08-17).

TDD: tests для core/ai/policy/enforcer/handle_mixin.py.

handle_mixin.py coverage baseline: 69% (per Sprint 222).
Target: 95%+ via these tests.

Coverage targets:
- _handle_guard_block: on_block=fail → raise, on_block=dlq → DLQ publish,
  on_block=warn → log only
- _publish_dlq: no _dlq_writer, with _dlq_writer, exception handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.ai.errors import GuardrailViolationError
from src.backend.core.ai.policy.enforcer.handle_mixin import HandleMixin


class _StubEnforcer(HandleMixin):
    """Minimal subclass to test mixin methods in isolation."""

    def __init__(self) -> None:
        self._dlq_writer: MagicMock | None = None


class TestHandleGuardBlockFail:
    """on_block=fail → raise GuardrailViolationError."""

    def test_on_block_fail_raises_guardrail_violation(self) -> None:
        enforcer = _StubEnforcer()

        with pytest.raises(GuardrailViolationError) as exc_info:
            enforcer._handle_guard_block(
                guard_name="test_guard",
                flagged=["test_category"],
                on_block="fail",
                content="blocked content",
            )

        assert exc_info.value.guard_name == "test_guard"
        assert exc_info.value.flagged_categories == ["test_category"]
        assert exc_info.value.on_block == "fail"
        assert exc_info.value.content == "blocked content"

    def test_on_block_fail_with_empty_flagged(self) -> None:
        enforcer = _StubEnforcer()

        with pytest.raises(GuardrailViolationError) as exc_info:
            enforcer._handle_guard_block(
                guard_name="test_guard",
                flagged=[],
                on_block="fail",
                content="blocked content",
            )

        assert exc_info.value.flagged_categories == []


class TestHandleGuardBlockDLQ:
    """on_block=dlq → publish to DLQ via TaskRegistry."""

    def test_on_block_dlq_creates_task(self) -> None:
        enforcer = _StubEnforcer()

        # Mock TaskRegistry to capture create_task call
        mock_task = MagicMock()
        mock_registry = MagicMock()
        mock_registry.create_task = MagicMock(return_value=mock_task)

        with patch(
            "src.backend.core.utils.task_registry.get_task_registry",
            return_value=mock_registry,
        ):
            enforcer._handle_guard_block(
                guard_name="test_guard",
                flagged=["category1"],
                on_block="dlq",
                content="blocked content",
            )

        # create_task was called once with name pattern
        mock_registry.create_task.assert_called_once()
        call_kwargs = mock_registry.create_task.call_args.kwargs
        assert "name" in call_kwargs
        assert "test_guard" in call_kwargs["name"]
        assert "policy-enforcer" in call_kwargs["name"]


class TestHandleGuardBlockWarn:
    """on_block=warn → log only (НЕ raise, НЕ DLQ)."""

    def test_on_block_warn_does_not_raise(self) -> None:
        enforcer = _StubEnforcer()
        # Should NOT raise
        enforcer._handle_guard_block(
            guard_name="test_guard",
            flagged=["test_category"],
            on_block="warn",
            content="flagged content",
        )

    def test_on_block_warn_does_not_create_task(self) -> None:
        enforcer = _StubEnforcer()
        with patch(
            "src.backend.core.utils.task_registry.get_task_registry",
        ) as mock_get:
            enforcer._handle_guard_block(
                guard_name="test_guard",
                flagged=["category"],
                on_block="warn",
                content="flagged",
            )
            # warn mode → no DLQ task created
            mock_get.assert_not_called()


class TestPublishDLQNoWriter:
    """_publish_dlq: no _dlq_writer → skip."""

    @pytest.mark.asyncio
    async def test_no_dlq_writer_skips_publish(self) -> None:
        enforcer = _StubEnforcer()
        enforcer._dlq_writer = None

        # DLQ module not available → skip via find_spec path
        with patch(
            "importlib.util.find_spec",
            return_value=None,
        ):
            # Should NOT raise, just log debug and return
            await enforcer._publish_dlq("guard", ["cat"], "content")

    @pytest.mark.asyncio
    async def test_dlq_module_not_available_skips(self) -> None:
        enforcer = _StubEnforcer()
        enforcer._dlq_writer = None

        with patch(
            "importlib.util.find_spec",
            return_value=None,
        ):
            await enforcer._publish_dlq("guard", ["cat"], "content")


class TestPublishDLQWithWriter:
    """_publish_dlq: with _dlq_writer → call writer.write(envelope)."""

    @pytest.mark.asyncio
    async def test_writer_called_with_envelope(self) -> None:
        enforcer = _StubEnforcer()
        mock_writer = MagicMock()
        mock_writer.write = AsyncMock()
        enforcer._dlq_writer = mock_writer

        with patch(
            "importlib.util.find_spec",
        ) as mock_find, patch(
            "src.backend.core.messaging.dlq.DLQEnvelope",
        ) as mock_envelope_cls, patch(
            "src.backend.core.messaging.dlq.DLQReason",
        ) as mock_reason:
            mock_find.return_value = MagicMock()
            mock_envelope = MagicMock()
            mock_envelope_cls.return_value = mock_envelope
            mock_reason.UNEXPECTED = "UNEXPECTED"

            await enforcer._publish_dlq(
                "test_guard",
                ["category1", "category2"],
                "blocked content here",
            )

        mock_writer.write.assert_awaited_once_with(mock_envelope)

    @pytest.mark.asyncio
    async def test_writer_exception_logged_but_not_raised(self) -> None:
        """Если writer.write throws → log error, НЕ raise."""
        enforcer = _StubEnforcer()
        mock_writer = MagicMock()
        mock_writer.write = AsyncMock(side_effect=RuntimeError("DLQ down"))
        enforcer._dlq_writer = mock_writer

        with patch(
            "importlib.util.find_spec",
        ) as mock_find, patch(
            "src.backend.core.messaging.dlq.DLQEnvelope",
        ), patch(
            "src.backend.core.messaging.dlq.DLQReason",
        ):
            mock_find.return_value = MagicMock()
            await enforcer._publish_dlq("guard", ["cat"], "content")

    @pytest.mark.asyncio
    async def test_content_truncated_to_200_chars(self) -> None:
        """Content > 200 chars truncated in envelope.original_payload."""
        enforcer = _StubEnforcer()
        mock_writer = MagicMock()
        mock_writer.write = AsyncMock()
        enforcer._dlq_writer = mock_writer

        long_content = "x" * 500

        with patch(
            "importlib.util.find_spec",
        ) as mock_find, patch(
            "src.backend.core.messaging.dlq.DLQEnvelope",
        ) as mock_envelope_cls, patch(
            "src.backend.core.messaging.dlq.DLQReason",
        ) as mock_reason:
            mock_find.return_value = MagicMock()
            mock_envelope = MagicMock()
            mock_envelope_cls.return_value = mock_envelope
            mock_reason.UNEXPECTED = "UNEXPECTED"

            await enforcer._publish_dlq("guard", ["cat"], long_content)

        call_kwargs = mock_envelope_cls.call_args.kwargs
        original_payload = call_kwargs["original_payload"]
        assert len(original_payload["content"]) == 200