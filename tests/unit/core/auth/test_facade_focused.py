"""Focused tests for ``AuthFacade`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/core/auth/facade.py`` с ~62% до ≥90%
путём детального покрытия AuthFacade + lazy accessors + singleton.

Контракт API:
- ``AuthFacade()`` — конструктор, lazy-инициализирует backend модули.
- ``AuthFacade.jwt`` — property: lazy import jwt_backend.
- ``AuthFacade.admin_roles`` — property: lazy import admin_role_resolver.
- ``AuthFacade.quotas`` — property: lazy import quotas.
- ``get_auth_facade()`` — singleton accessor (Lazy pattern).
- ``AuthResult`` — re-export из auth_result.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.auth import facade as auth_facade_mod
from src.backend.core.auth.auth_result import AuthResult
from src.backend.core.auth.facade import AuthFacade, get_auth_facade


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Сбрасывает singleton перед каждым тестом."""
    auth_facade_mod._auth_facade = None
    yield
    auth_facade_mod._auth_facade = None


class TestAuthFacadeInit:
    """``AuthFacade.__init__`` — lazy initialization."""

    def test_init_creates_instance(self) -> None:
        """``AuthFacade()`` создаётся без ошибок."""
        f = AuthFacade()
        assert f is not None

    def test_init_backends_none(self) -> None:
        """Все backends — None после init (lazy)."""
        f = AuthFacade()
        assert f._jwt_backend is None
        assert f._admin_roles is None
        assert f._quotas is None


class TestAuthFacadeJwtProperty:
    """``AuthFacade.jwt`` — lazy accessor."""

    def test_jwt_first_access_imports(self) -> None:
        """First access to .jwt triggers import."""
        f = AuthFacade()
        assert f._jwt_backend is None
        # Access triggers import.
        backend = f.jwt
        assert backend is not None
        assert f._jwt_backend is backend

    def test_jwt_cached_after_first_access(self) -> None:
        """Second access returns cached value."""
        f = AuthFacade()
        first = f.jwt
        second = f.jwt
        assert first is second  # cached

    def test_jwt_module_has_encode_decode(self) -> None:
        """``jwt`` backend module exposes encode/decode functions."""
        f = AuthFacade()
        backend = f.jwt
        # Module-level functions available.
        assert hasattr(backend, "encode")
        assert hasattr(backend, "decode")


class TestAuthFacadeAdminRolesProperty:
    """``AuthFacade.admin_roles`` — lazy accessor."""

    def test_admin_roles_first_access_imports(self) -> None:
        """First access to .admin_roles triggers import."""
        f = AuthFacade()
        assert f._admin_roles is None
        resolver = f.admin_roles
        assert resolver is not None
        assert f._admin_roles is resolver

    def test_admin_roles_cached_after_first_access(self) -> None:
        """Second access returns cached value."""
        f = AuthFacade()
        first = f.admin_roles
        second = f.admin_roles
        assert first is second


class TestAuthFacadeQuotasProperty:
    """``AuthFacade.quotas`` — lazy accessor."""

    def test_quotas_first_access_imports(self) -> None:
        """First access to .quotas triggers import."""
        f = AuthFacade()
        assert f._quotas is None
        q = f.quotas
        assert q is not None
        assert f._quotas is q

    def test_quotas_cached_after_first_access(self) -> None:
        """Second access returns cached value."""
        f = AuthFacade()
        first = f.quotas
        second = f.quotas
        assert first is second


class TestGetAuthFacadeSingleton:
    """``get_auth_facade()`` — singleton pattern."""

    def test_get_auth_facade_returns_instance(self) -> None:
        """``get_auth_facade()`` возвращает AuthFacade instance."""
        f = get_auth_facade()
        assert isinstance(f, AuthFacade)

    def test_get_auth_facade_singleton(self) -> None:
        """``get_auth_facade()`` возвращает тот же instance."""
        f1 = get_auth_facade()
        f2 = get_auth_facade()
        assert f1 is f2

    def test_singleton_state_preserved(self) -> None:
        """State singleton'а сохраняется между вызовами."""
        f1 = get_auth_facade()
        # Trigger lazy import.
        _ = f1.jwt
        f2 = get_auth_facade()
        # Backend cached in singleton.
        assert f2._jwt_backend is not None
        assert f2._jwt_backend is f1._jwt_backend


class TestAuthResultReExport:
    """``AuthResult`` re-exported из auth_result."""

    def test_auth_result_in_facade_module(self) -> None:
        """``AuthResult`` доступен через facade module."""
        assert hasattr(auth_facade_mod, "AuthResult")

    def test_auth_result_same_class(self) -> None:
        """``AuthResult`` в facade — тот же класс что в auth_result."""
        assert auth_facade_mod.AuthResult is AuthResult


class TestFacadeModuleExports:
    """``__all__`` exports."""

    def test_all_count(self) -> None:
        """``__all__`` содержит 3 symbols."""
        assert len(auth_facade_mod.__all__) == 3

    def test_all_present(self) -> None:
        """Все exports — классы или функции."""
        for name in auth_facade_mod.__all__:
            obj = getattr(auth_facade_mod, name)
            assert isinstance(obj, type) or callable(obj)

    def test_all_names(self) -> None:
        """Конкретные имена в ``__all__``."""
        assert "AuthFacade" in auth_facade_mod.__all__
        assert "AuthResult" in auth_facade_mod.__all__
        assert "get_auth_facade" in auth_facade_mod.__all__


class TestFacadeInheritance:
    """``AuthFacade`` наследует миксины."""

    def test_inherits_token_mixin(self) -> None:
        """``AuthFacade`` — подкласс ``AuthTokenMixin``."""
        from src.backend.core.auth.facade_token_mixin import AuthTokenMixin

        assert issubclass(AuthFacade, AuthTokenMixin)

    def test_inherits_verify_mixin(self) -> None:
        """``AuthFacade`` — подкласс ``AuthVerifyMixin``."""
        from src.backend.core.auth.facade_verify_mixin import AuthVerifyMixin

        assert issubclass(AuthFacade, AuthVerifyMixin)

    def test_inherits_core_mixin(self) -> None:
        """``AuthFacade`` — подкласс ``AuthCoreMixin``."""
        from src.backend.core.auth.facade_core_mixin import AuthCoreMixin

        assert issubclass(AuthFacade, AuthCoreMixin)


class TestFacadeLazyImportsOrderIndependent:
    """Lazy accessors можно вызывать в любом порядке."""

    def test_access_quotas_first(self) -> None:
        """``.quotas`` до ``.jwt`` работает."""
        f = AuthFacade()
        q = f.quotas
        assert q is not None
        # jwt ещё None.
        assert f._jwt_backend is None
        # Теперь jwt.
        j = f.jwt
        assert j is not None

    def test_access_all_three(self) -> None:
        """Все три backends загружаются независимо."""
        f = AuthFacade()
        j = f.jwt
        a = f.admin_roles
        q = f.quotas
        assert j is not None
        assert a is not None
        assert q is not None
        # Все cached.
        assert f._jwt_backend is j
        assert f._admin_roles is a
        assert f._quotas is q
