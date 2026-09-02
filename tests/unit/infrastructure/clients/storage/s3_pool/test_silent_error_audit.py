"""Unit-тесты ``infrastructure.clients.storage.s3_pool`` — Sprint C2 (S50 P0 #9).

S48 swarm audit (A2 Infra #9): ``put_object/copy_object/delete_object/
delete_objects`` возвращали ``{"status": "error"}`` dict при BotoClientError
без observability → callers могли проигнорировать → потерянные данные/удаления.

S49 fix: 3 из 4 sites добавили ``self._emit_s3_silent_error_audit(...)``.
S50 Sprint C2 fix:
1. ``copy_object`` — добавил аудит-emit (missing ранее).
2. ``delete_object`` — удалён dead-code duplicate ``except BotoClientError``
   блок (Python unreachable после первого except).
3. Тесты: verify audit emit для всех 4 sites + verify dead-code removed.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.storage.s3_pool.client import (
    BotoClientError,
    S3Client,
)


def _make_pool() -> S3Client:
    """Construct S3Client без реального boto3 import (для unit-тестов)."""
    pool = S3Client.__new__(S3Client)
    pool.logger = MagicMock()
    pool._client = MagicMock()  # type: ignore[attr-defined]
    pool._settings = MagicMock(bucket="test-bucket")  # type: ignore[attr-defined]
    # NOTE: НЕ мокаем ``_emit_s3_silent_error_audit`` — это async def → тестам
    # нужно вызывать реальный method, чтобы verify audit flow.
    return pool


def _make_pool_with_audit_mock() -> S3Client:
    """Pool с мокнутым ``_emit_s3_silent_error_audit`` для проверки call args."""
    pool = _make_pool()
    pool._emit_s3_silent_error_audit = MagicMock()  # type: ignore[method-assign]
    return pool


def _patch_is_connected(pool: S3Client) -> MagicMock:
    """Patch ``is_connected`` property → True (bypass ensure_connected)."""
    return patch.object(  # noqa: SIM117
        type(pool), "is_connected", new_callable=lambda: lambda self: True
    )


@pytest.mark.unit
class TestS3SilentErrorAuditEmission:
    """S49/S50: каждый silent-error site должен emit audit-event."""

    def test_put_object_method_has_audit_emit(self) -> None:
        """``put_object`` вызывает ``_emit_s3_silent_error_audit`` в except."""
        src = inspect.getsource(S3Client.put_object)
        assert "self._emit_s3_silent_error_audit" in src
        assert '"put_object"' in src

    def test_delete_object_method_has_audit_emit(self) -> None:
        """``delete_object`` вызывает ``_emit_s3_silent_error_audit``."""
        src = inspect.getsource(S3Client.delete_object)
        assert "self._emit_s3_silent_error_audit" in src
        assert '"delete_object"' in src

    def test_delete_objects_method_has_audit_emit(self) -> None:
        """``delete_objects`` вызывает ``_emit_s3_silent_error_audit``."""
        src = inspect.getsource(S3Client.delete_objects)
        assert "self._emit_s3_silent_error_audit" in src
        assert '"delete_objects"' in src

    def test_copy_object_method_has_audit_emit(self) -> None:
        """``copy_object`` — Sprint C2 FIX: добавлен audit emit (was missing)."""
        src = inspect.getsource(S3Client.copy_object)
        assert "self._emit_s3_silent_error_audit" in src, (
            "copy_object must emit audit on BotoClientError (S50 Sprint C2)"
        )
        assert '"copy_object"' in src


@pytest.mark.unit
class TestS3SilentErrorAuditHelper:
    """``_emit_s3_silent_error_audit`` — emit pattern."""

    def test_emit_helper_calls_audit_safe(self) -> None:
        """``_emit_s3_silent_error_audit`` delegates to ``emit_audit_safe``."""
        pool = _make_pool()
        # Patch ``emit_audit_safe`` в namespace где helper импортирует.
        with patch(
            "src.backend.core.audit.facade._base.emit_audit_safe"
        ) as mock_emit:
            exc = RuntimeError("test error")
            # Production method is sync (not async def) — calls emit_audit_safe directly.
            pool._emit_s3_silent_error_audit("put_object", exc)
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event"] == "storage.s3.silent_error"
            assert call_kwargs["action"] == "s3_put_object"
            assert call_kwargs["outcome"] == "failure"
            assert call_kwargs["severity"] == "error"

    def test_emit_helper_documents_warning(self) -> None:
        """``_emit_s3_silent_error_audit`` docstring упоминает M1-#9 + 22 callers."""
        doc = S3Client._emit_s3_silent_error_audit.__doc__
        assert doc is not None
        assert "M1-#9" in doc
        assert "22 callers" in doc
        assert "raise вместо dict" in doc


@pytest.mark.unit
class TestS3DeleteObjectDeadCodeRemoval:
    """S50 Sprint C2: dead-code duplicate ``except BotoClientError`` block удалён."""

    def test_delete_object_has_single_except_block(self) -> None:
        """``delete_object`` имеет ровно один ``except BotoClientError`` block."""
        src = inspect.getsource(S3Client.delete_object)
        count = src.count("except BotoClientError as exc:")
        assert count == 1, (
            f"delete_object must have exactly 1 except BotoClientError block, "
            f"found {count} (Sprint C2 dead-code removal)"
        )

    def test_delete_object_emits_audit_once_on_error(self) -> None:
        """При исключении audit-emit вызывается ровно один раз (не дважды)."""
        # Static check: один вызов audit внутри одного except block.
        src = inspect.getsource(S3Client.delete_object)
        audit_call_count = src.count(
            "self._emit_s3_silent_error_audit(\"delete_object\""
        )
        assert audit_call_count == 1


@pytest.mark.unit
class TestS3SilentErrorReturnShape:
    """Regression: return shape остаётся ``{"status": "error", "message": ...}``.

    Sprint C2 НЕ меняет contract — только добавляет audit. Caller behavior
    не ломается. Полный fix (raise вместо dict) — deferred (breaking change
    для 22 callers per inline comment).
    """

    @pytest.mark.asyncio
    async def test_put_object_returns_error_dict_on_boto_error(self) -> None:
        """``put_object`` на BotoClientError → dict (не raise)."""

        pool = _make_pool_with_audit_mock()

        async def fake_put(**kwargs):
            raise BotoClientError(
                error_response={"Error": {"Code": "AccessDenied", "Message": "denied"}},
                operation_name="PutObject",
            )

        pool._client.put_object = fake_put

        with patch.object(type(pool), "is_connected", new_callable=lambda: lambda self: True):
            with patch.object(pool, "client_context") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(
                    return_value=pool._client
                )
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await pool.put_object(
                    key="k", body=b"x", metadata={}
                )
        assert result["status"] == "error"
        assert "message" in result
        assert "denied" in result["message"].lower() or "AccessDenied" in result["message"]
        # Audit emit called
        pool._emit_s3_silent_error_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_copy_object_returns_error_dict_on_boto_error(self) -> None:
        """``copy_object`` на BotoClientError → dict + audit emit (S50 fix)."""

        pool = _make_pool_with_audit_mock()

        async def fake_copy(**kwargs):
            raise BotoClientError(
                error_response={"Error": {"Code": "SlowDown", "Message": "throttled"}},
                operation_name="CopyObject",
            )

        pool._client.copy_object = fake_copy

        with patch.object(type(pool), "is_connected", new_callable=lambda: lambda self: True):
            with patch.object(pool, "client_context") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(
                    return_value=pool._client
                )
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await pool.copy_object(
                    source_key="src", dest_key="dst"
                )
        assert result["status"] == "error"
        assert "throttled" in result["message"].lower() or "SlowDown" in result["message"]
        # Sprint C2 fix: audit emit added
        pool._emit_s3_silent_error_audit.assert_called_once()
        # Audit call args: ("copy_object", exc)
        args = pool._emit_s3_silent_error_audit.call_args[0]
        assert args[0] == "copy_object"
        assert isinstance(args[1], BotoClientError)
