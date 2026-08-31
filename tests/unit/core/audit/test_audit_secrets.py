"""Unit-тесты ``core.audit.facade.secrets`` — coverage ratchet slice 3 (S47 W6).

S44 W32 baseline: ``src/backend/core/audit/facade/secrets.py`` — 46%.
Цель slice: поднять до ≥90%, покрывая:
* ``emit_secret_rotation`` со всеми kwargs и error_class=None vs not-None;
* ``emit_secret_access`` — cache hit/miss, success/failure, error_class;
* narrow exception handling (ImportError/AttributeError/RuntimeError)
  per cycle-9/D-AUDIT-1033.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.core.audit.facade.secrets import (
    emit_secret_access,
    emit_secret_rotation,
)


@pytest.fixture
def captured_emits() -> list[dict[str, object]]:
    """Список перехваченных kwargs, переданных в ``emit_audit``."""
    return []


@pytest.fixture
def mock_emit_audit(captured_emits: list[dict[str, object]]) -> None:
    """Подменяет ``emit_audit`` в submodule на capture-list appender."""
    async def fake_emit_audit(**kwargs: object) -> None:
        captured_emits.append(kwargs)

    sync_def = lambda **kwargs: captured_emits.append(kwargs) or None  # noqa: E731

    with patch(
        "src.backend.core.audit.facade.secrets.emit_audit",
        side_effect=sync_def,
    ):
        yield


@pytest.mark.unit
class TestEmitSecretRotation:
    """``emit_secret_rotation`` — sync wrapper (Path A pattern C)."""

    def test_emits_rotation_event_with_full_kwargs(
        self,
        captured_emits: list[dict[str, object]],
    ) -> None:
        """``emit_secret_rotation`` формирует details + передаёт все kwargs."""
        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=lambda **kw: captured_emits.append(kw) or None,
        ):
            result = emit_secret_rotation(
                secret_path="vault:db/pwd",
                rotation_id="rot-001",
                correlation_id="corr-xyz",
                actor="admin:alice",
                outcome="success",
            )
        assert result is None  # sync, no await
        assert len(captured_emits) == 1
        call = captured_emits[0]
        assert call["event"] == "secret.rotation"
        assert call["actor"] == "admin:alice"
        assert call["resource"] == "vault:db/pwd"
        assert call["action"] == "rotate"
        assert call["outcome"] == "success"
        details = call["details"]
        assert details["secret_path"] == "vault:db/pwd"
        assert details["rotation_id"] == "rot-001"
        assert details["correlation_id"] == "corr-xyz"
        assert "error_class" not in details  # None → key omitted

    def test_emits_rotation_with_error_class(
        self,
        captured_emits: list[dict[str, object]],
    ) -> None:
        """``error_class`` not-None → добавляется в details."""
        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=lambda **kw: captured_emits.append(kw) or None,
        ):
            emit_secret_rotation(
                secret_path="vault:api/token",
                rotation_id="rot-002",
                correlation_id="corr-fail",
                actor="system:scheduler",
                outcome="failure",
                error_class="VaultConnectionError",
            )
        assert len(captured_emits) == 1
        details = captured_emits[0]["details"]
        assert details["error_class"] == "VaultConnectionError"
        assert captured_emits[0]["outcome"] == "failure"


@pytest.mark.unit
class TestEmitSecretAccess:
    """``emit_secret_access`` — async с narrow exception handling (D-AUDIT-1033)."""

    @pytest.mark.asyncio
    async def test_emits_access_event_cache_hit_success(
        self,
        captured_emits: list[dict[str, object]],
    ) -> None:
        """``emit_secret_access`` — cache hit, success path."""
        async def fake_emit(**kw: object) -> None:
            captured_emits.append(kw)

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            await emit_secret_access(
                credential_name="db_pwd",
                secret_ref="vault:db/pwd",
                actor="service:api",
                outcome="success",
                cache_status="hit",
                resolution_id="res-42",
            )
        assert len(captured_emits) == 1
        call = captured_emits[0]
        assert call["event"] == "secret.access"
        assert call["action"] == "resolve"
        assert call["resource"] == "vault:db/pwd"
        details = call["details"]
        assert details["credential_name"] == "db_pwd"
        assert details["cache_status"] == "hit"
        assert details["resolution_id"] == "res-42"
        assert "error_class" not in details

    @pytest.mark.asyncio
    async def test_emits_access_event_cache_miss_failure_with_error(
        self,
        captured_emits: list[dict[str, object]],
    ) -> None:
        """``emit_secret_access`` — cache miss, failure с error_class."""
        async def fake_emit(**kw: object) -> None:
            captured_emits.append(kw)

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            await emit_secret_access(
                credential_name="api_token",
                secret_ref="env:API_TOKEN",
                actor="user:bob",
                outcome="failure",
                cache_status="miss",
                error_class="KeyError",
            )
        assert len(captured_emits) == 1
        details = captured_emits[0]["details"]
        assert details["cache_status"] == "miss"
        assert details["error_class"] == "KeyError"
        assert "resolution_id" not in details  # None → key omitted

    @pytest.mark.asyncio
    async def test_swallows_import_error(self) -> None:
        """``ImportError`` от ``emit_audit`` → swallowed + DEBUG log, no raise."""
        async def fake_emit(**kw: object) -> None:
            raise ImportError("audit facade missing")

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            # Не должно raise.
            await emit_secret_access(
                credential_name="x",
                secret_ref="vault:x",
                actor="system",
                outcome="success",
                cache_status="hit",
            )

    @pytest.mark.asyncio
    async def test_swallows_attribute_error(self) -> None:
        """``AttributeError`` → swallowed (API change)."""
        async def fake_emit(**kw: object) -> None:
            raise AttributeError("emit_audit missing")

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            await emit_secret_access(
                credential_name="x",
                secret_ref="vault:x",
                actor="system",
                outcome="success",
                cache_status="hit",
            )

    @pytest.mark.asyncio
    async def test_swallows_runtime_error(self) -> None:
        """``RuntimeError`` → swallowed (backend unavailable)."""
        async def fake_emit(**kw: object) -> None:
            raise RuntimeError("backend unavailable")

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            await emit_secret_access(
                credential_name="x",
                secret_ref="vault:x",
                actor="system",
                outcome="success",
                cache_status="hit",
            )

    @pytest.mark.asyncio
    async def test_does_not_swallow_unexpected_exception(self) -> None:
        """``ValueError`` (не в narrow-list) → пробрасывается."""
        async def fake_emit(**kw: object) -> None:
            raise ValueError("unexpected")

        with patch(
            "src.backend.core.audit.facade.secrets.emit_audit",
            side_effect=fake_emit,
        ):
            with pytest.raises(ValueError, match="unexpected"):
                await emit_secret_access(
                    credential_name="x",
                    secret_ref="vault:x",
                    actor="system",
                    outcome="success",
                    cache_status="hit",
                )
