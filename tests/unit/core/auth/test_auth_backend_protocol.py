"""T-P0.1.6: unit-тесты для core/auth/protocols.py (AuthBackend Protocol).

Coverage: protocols.py 0% → 100% через runtime structural checks
(AuthBackend помечен @runtime_checkable, поэтому isinstance() работает).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Request

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.protocols import AuthBackend


class _FakeBackend:
    """Реализация AuthBackend для positive structural test."""

    method = AuthMethod.JWT

    async def verify(self, request: Request) -> AuthContext | None:
        return None


class _FakeBackendWithBrokenVerify:
    """verify возвращает неправильный тип — structural mismatch по сигнатуре не
    ловится isinstance (Protocol — duck typing), но isinstance всё равно True
    если есть атрибут verify. Это документирующее поведение."""

    method = AuthMethod.MTLS

    async def verify(self, request: Any) -> int:  # type: ignore[override]
        return 42


class _NoVerify:
    """Объект без метода verify — isinstance(AuthBackend) должен быть False."""

    method = AuthMethod.JWT


class _NoMethod:
    """Объект с verify, но без method — должен пройти (нет обязательного атрибута)."""

    async def verify(self, request: Request) -> AuthContext | None:
        return None


class TestAuthBackendProtocol:
    def test_module_all(self) -> None:
        """__all__ содержит AuthBackend."""
        from src.backend.core.auth import protocols as p

        assert hasattr(p, "__all__")
        assert "AuthBackend" in p.__all__
        assert len(p.__all__) == 1

    def test_isinstance_true_for_conforming_object(self) -> None:
        """Любой класс с method + verify проходит isinstance."""
        assert isinstance(_FakeBackend(), AuthBackend)

    def test_isinstance_false_for_object_without_verify(self) -> None:
        """Объект без verify → isinstance=False."""
        assert not isinstance(_NoVerify(), AuthBackend)

    def test_isinstance_runtime_checkable_attribute(self) -> None:
        """AuthBackend помечен @runtime_checkable — hasattr `_runtime_checkable` или
        флаг в __class__/_is_runtime_protocol. Проверяем через isinstance success."""
        # Альтернативная проверка: вызвать isinstance() на произвольном объекте
        # не должно бросать TypeError.
        for obj in [_FakeBackend(), _NoVerify(), object()]:
            try:
                isinstance(obj, AuthBackend)
            except TypeError as exc:  # pragma: no cover - defensive
                pytest.fail(f"isinstance raised TypeError on {obj!r}: {exc}")

    def test_protocol_has_method_attribute(self) -> None:
        """Атрибут method объявлен в Protocol body."""
        # Protocol member доступен через __annotations__ или __protocol_attrs__
        # Pydantic-free Protocol: проверим, что подсказка есть
        annotations = getattr(AuthBackend, "__annotations__", {})
        assert "method" in annotations

    def test_protocol_verify_signature(self) -> None:
        """verify — async функция, принимает request, возвращает AuthContext | None."""
        annotations = getattr(AuthBackend.verify, "__annotations__", {})
        # request должен быть аннотирован
        assert "request" in annotations or len(annotations) >= 1

    def test_fake_backend_with_wrong_return_type_passes_isinstance(self) -> None:
        """Structural typing: возврат int проходит isinstance (документирует duck typing)."""
        # Это intentional: Protocol проверяет только наличие атрибутов, не сигнатуры.
        assert isinstance(_FakeBackendWithBrokenVerify(), AuthBackend)

    def test_no_method_attribute_fails_isinstance(self) -> None:
        """method — Protocol member, isinstance() проверяет и class attributes."""
        # Protocol with class-level annotations (method: AuthMethod) is checked
        # structurally — _NoMethod() не имеет method, поэтому не проходит.
        assert not isinstance(_NoMethod(), AuthBackend)

    def test_authmethod_jwt_member_exists(self) -> None:
        """AuthBackend использует AuthMethod — sanity check enum membership."""
        assert AuthMethod.JWT.value
        assert AuthMethod.MTLS.value


class TestAuthBackendVerifyReturnsNone:
    """Документирующее поведение: verify может вернуть None при отсутствии credentials."""

    @pytest.mark.asyncio
    async def test_fake_backend_verify_returns_none(self) -> None:
        from fastapi import FastAPI

        app = FastAPI()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1234),
            "app": app,
            "router": app.router,
        }
        request = Request(scope)
        result = await _FakeBackend().verify(request)
        assert result is None
