"""Regression-блокировка для NEW-1 fix: Service.helper AttributeError.

Pre-NEW-1: ``BaseService.__init__`` имел строку
``self.helper = self.HelperMethods(repo)`` где ``HelperMethods``
— это только type-annotation declared на классе, НЕ значение.
→ ``AttributeError: 'OrderService' object has no attribute 'HelperMethods'``
при создании любого *Service instance (orders/users/files/etc).

NEW-1 fix (2026-08-13): заменено на
``self.helper = repo.helper if repo is not None else None``
— ``helper`` создаётся в ``SQLAlchemyRepository.__init__`` (с правильными
``model``/``load_joined_models``/``main_class``), просто проксируется.

Тесты:

1. Service с repo=None не падает в __init__.
2. Service с repo получает helper от repo (proxy).
3. helper attribute не падает AttributeError при создании instance.
"""

from __future__ import annotations


class _FakeRepo:
    """Минимальный fake для теста — имеет ``helper`` attribute."""

    def __init__(self) -> None:
        self.helper = "fake-helper-marker"


def test_service_with_repo_none_does_not_raise() -> None:
    """Service(repo=None) не падает (HelperMethods attribute missing)."""
    from src.backend.services.core.base import BaseService

    class _TestService(BaseService):
        pass

    svc = _TestService(repo=None, response_schema=None, request_schema=None)
    assert svc.helper is None


def test_service_with_repo_uses_repo_helper() -> None:
    """Service(repo=fake) устанавливает helper=repo.helper (proxy)."""
    from src.backend.services.core.base import BaseService

    class _TestService(BaseService):
        pass

    fake_repo = _FakeRepo()
    svc = _TestService(
        repo=fake_repo, response_schema=None, request_schema=None,
    )
    assert svc.helper == "fake-helper-marker"


def test_helper_attr_does_not_raise_attributeerror() -> None:
    """Specific regression check — НЕ ловим AttributeError на init."""
    from src.backend.services.core.base import BaseService

    class _TestService(BaseService):
        pass

    # Раньше это падало: AttributeError: '_TestService' object has no attribute 'HelperMethods'
    # Сейчас — корректно создаётся.
    try:
        svc = _TestService(repo=_FakeRepo(), response_schema=None, request_schema=None)
    except AttributeError as exc:
        raise AssertionError(
            f"NEW-1 fix regressed: AttributeError raised on init: {exc}",
        ) from exc
    assert svc.helper is not None
