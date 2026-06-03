"""Unit tests for src.backend.core.ai.errors."""

from __future__ import annotations

import pytest

from src.backend.core.ai.errors import (
    AIFsError,
    AIWorkspaceError,
    FsForbiddenWriteError,
    GuardrailViolationError,
    GuardResult,
    WorkspaceQuotaExceededError,
    WorkspaceTTLExpiredError,
)


class TestGuardResult:
    def test_defaults(self) -> None:
        gr = GuardResult(guard_name="g1", verdict="passed")
        assert gr.guard_name == "g1"
        assert gr.verdict == "passed"
        assert gr.categories == []

    def test_with_categories(self) -> None:
        gr = GuardResult(
            guard_name="g1", verdict="blocked", categories=["hate", "violence"]
        )
        assert gr.categories == ["hate", "violence"]


class TestGuardrailViolationError:
    def test_attributes(self) -> None:
        exc = GuardrailViolationError(
            guard_name="llama",
            flagged_categories=["violence"],
            on_block="dlq",
            content="x" * 500,
        )
        assert exc.guard_name == "llama"
        assert exc.flagged_categories == ["violence"]
        assert exc.on_block == "dlq"
        assert len(exc.content) == 200
        assert "llama" in str(exc)
        assert "blocked" in str(exc)

    def test_default_on_block_and_content(self) -> None:
        exc = GuardrailViolationError(
            guard_name="g1", flagged_categories=["spam"]
        )
        assert exc.on_block == "fail"
        assert exc.content == ""


class TestAIWorkspaceError:
    def test_is_exception(self) -> None:
        with pytest.raises(AIWorkspaceError):
            raise AIWorkspaceError("boom")


class TestWorkspaceQuotaExceededError:
    def test_message(self) -> None:
        exc = WorkspaceQuotaExceededError(
            tenant="t1", used_bytes=100, quota_bytes=50
        )
        assert exc.tenant == "t1"
        assert exc.used_bytes == 100
        assert exc.quota_bytes == 50
        assert "t1" in str(exc)
        assert "100 / 50" in str(exc)


class TestWorkspaceTTLExpiredError:
    def test_message(self) -> None:
        exc = WorkspaceTTLExpiredError(
            session_id="s1", age_seconds=120.5, ttl_seconds=60.0
        )
        assert exc.session_id == "s1"
        assert exc.age_seconds == 120.5
        assert exc.ttl_seconds == 60.0
        assert "s1" in str(exc)
        assert "120s > 60s" in str(exc)


class TestAIFsError:
    def test_is_exception(self) -> None:
        with pytest.raises(AIFsError):
            raise AIFsError("fail")


class TestFsForbiddenWriteError:
    def test_message(self) -> None:
        exc = FsForbiddenWriteError(path="/workspace/x", reason="outside workspace")
        assert exc.path == "/workspace/x"
        assert exc.reason == "outside workspace"
        assert "/workspace/x" in str(exc)
