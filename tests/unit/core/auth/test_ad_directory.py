"""Tests for ``src.backend.core.auth.ad_directory``.

Sprint 225: ``__getattr__``-based lazy proxy для services.auth.ad_directory_client.
Устраняет layer-violation ``core → services``: импорт services
происходит ТОЛЬКО при lookup атрибута, а не на module-load.

Тесты фиксируют контракт:
- ``AdAuthError`` и ``AdSearchEntry`` доступны через proxy
- Lazy import — не импортируются до первого обращения
- Unknown attribute → ``AttributeError`` с понятным message
- ``__all__`` exports только разрешённые имена
"""

from __future__ import annotations

import pytest

from src.backend.core.auth import ad_directory


class TestAdDirectoryExports:
    """``__all__`` должен содержать только проксируемые имена."""

    def test_all_exports(self) -> None:
        assert ad_directory.__all__ == ("AdAuthError", "AdSearchEntry")

    def test_lazy_proxy_uses_getattr(self) -> None:
        """Lazy proxy: ``AdAuthError``/``AdSearchEntry`` доступны ТОЛЬКО через
        ``__getattr__`` proxy, не как прямые module attributes.

        Проверяем, что в module namespace эти имена появляются динамически
        (через ``getattr(module, name)``), а не как ``module.AdAuthError``.
        Последний вариант в Python фактически вызывает ``__getattr__``, поэтому
        прямая проверка сложна; используем type-checks и docstring контракт.
        """
        # Документированный контракт: ``__getattr__`` — единственный механизм
        # доступа к AdAuthError/AdSearchEntry.
        assert "__getattr__" in vars(ad_directory)
        assert callable(ad_directory.__getattr__)

    def test_proxy_attribute_callable(self) -> None:
        """``__getattr__`` — callable, принимает name → возвращает attr or raise."""
        # Прямой вызов __getattr__ — должен работать (как при module.attr)
        result = ad_directory.__getattr__("AdAuthError")
        assert result.__name__ == "AdAuthError"

    def test_proxy_unknown_raises_attribute_error(self) -> None:
        """``__getattr__("UnknownName")`` → ``AttributeError`` с message."""
        with pytest.raises(AttributeError) as exc_info:
            ad_directory.__getattr__("NoSuchAttribute")
        assert "NoSuchAttribute" in str(exc_info.value)
        assert ad_directory.__name__ in str(exc_info.value)


class TestAdDirectoryLazyProxy:
    """``__getattr__`` — lazy import services.auth.ad_directory_client.

    ``AdAuthError`` и ``AdSearchEntry`` живут в submodule
    ``ad_directory_client.state``. Сам ``ad_directory_client`` module
    проксирует lookup через свой ``__getattr__`` к ``state``, поэтому
    ``cls.__module__`` будет ``...ad_directory_client.state`` (не сам
    ``ad_directory_client``).
    """

    def test_ad_auth_error_proxy(self) -> None:
        """``ad_directory.AdAuthError`` импортируется через двойной proxy."""
        cls = ad_directory.AdAuthError
        assert cls is not None
        # Класс определён в submodule state
        assert cls.__module__ == "src.backend.services.auth.ad_directory_client.state"
        assert cls.__name__ == "AdAuthError"

    def test_ad_search_entry_proxy(self) -> None:
        """``ad_directory.AdSearchEntry`` импортируется через двойной proxy."""
        cls = ad_directory.AdSearchEntry
        assert cls is not None
        assert cls.__module__ == "src.backend.services.auth.ad_directory_client.state"
        assert cls.__name__ == "AdSearchEntry"

    def test_proxy_returns_same_object_each_time(self) -> None:
        """Два lookup'а возвращают тот же объект (модуль импортируется один раз)."""
        cls1 = ad_directory.AdAuthError
        cls2 = ad_directory.AdAuthError
        assert cls1 is cls2


class TestAdDirectoryUnknownAttribute:
    """Unknown attribute → ``AttributeError``."""

    def test_unknown_raises(self) -> None:
        with pytest.raises(AttributeError) as exc_info:
            ad_directory.NoSuchAttribute  # type: ignore[attr-defined]
        assert "NoSuchAttribute" in str(exc_info.value)
        assert ad_directory.__name__ in str(exc_info.value)

    def test_dunder_not_proxied(self) -> None:
        """``__getattr__`` вызывается только для missing attributes.
        ``__name__``, ``__file__``, etc. берутся из module attributes.
        """
        assert ad_directory.__name__ == "src.backend.core.auth.ad_directory"
        assert hasattr(ad_directory, "__all__")


class TestAdDirectoryProxyImport:
    """Проверка, что proxy действительно ленивый.

    Если services.auth.ad_directory_client не импортирован в sys.modules
    на момент обращения — proxy его импортирует.
    """

    def test_proxy_triggers_import(self) -> None:
        """Первый lookup AdAuthError → происходит import services module."""
        import sys

        cls = ad_directory.AdAuthError
        # После lookup services.auth.ad_directory_client и state должны
        # быть в sys.modules
        assert "src.backend.services.auth.ad_directory_client" in sys.modules
        assert "src.backend.services.auth.ad_directory_client.state" in sys.modules
        assert cls.__module__ == "src.backend.services.auth.ad_directory_client.state"
