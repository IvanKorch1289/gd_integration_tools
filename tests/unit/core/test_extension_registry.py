"""Контракт-тесты реестра ресурсов расширений (ADR-0457).

Проверяют инверсию зависимостей ``src/ → extensions``: реестр живёт в core,
расширения **отдают** ресурсы, потребители **забирают** их по ключу.
"""

from __future__ import annotations

import pytest

from src.backend.core.extension_registry import (
    ExtensionResource,
    ExtensionResourceRegistry,
    get_extension_registry,
    get_extension_resource,
    register_extension_resource,
    reset_extension_resources,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry():
    """Сбрасывает process-wide реестр до/после теста."""
    reset_extension_resources()
    yield
    reset_extension_resources()


class TestExtensionResourceRegistry:
    """Поведение хранилища ресурсов."""

    def test_register_and_find(self) -> None:
        """Зарегистрированный ресурс находится по ключу (domain, kind, name)."""
        registry = ExtensionResourceRegistry()
        registry.register(ExtensionResource("orders", "schema", "schema_in", int))

        assert registry.find("orders", "schema", "schema_in") is int
        assert registry.get("orders", "schema", "schema_in") is int

    def test_find_missing_returns_none(self) -> None:
        """Отсутствующий ресурс — ``None``, а не исключение."""
        registry = ExtensionResourceRegistry()

        assert registry.find("orders", "schema", "nope") is None

    def test_get_missing_raises_keyerror(self) -> None:
        """``get`` без ресурса → ``KeyError`` с понятным текстом."""
        registry = ExtensionResourceRegistry()

        with pytest.raises(KeyError) as exc:
            registry.get("orders", "schema", "schema_in")

        message = str(exc.value)
        assert "orders" in message
        assert "schema_in" in message

    def test_re_registration_replaces_value(self) -> None:
        """Повторная регистрация того же ключа перезаписывает значение."""
        registry = ExtensionResourceRegistry()
        registry.register(ExtensionResource("orders", "schema", "schema_in", int))
        registry.register(ExtensionResource("orders", "schema", "schema_in", str))

        assert registry.get("orders", "schema", "schema_in") is str

    def test_domains_are_sorted(self) -> None:
        """Список доменов отсортирован и уникален."""
        registry = ExtensionResourceRegistry()
        registry.register(ExtensionResource("users", "service", "users", int))
        registry.register(ExtensionResource("orders", "schema", "schema_in", int))
        registry.register(ExtensionResource("orders", "service", "orders", int))

        assert registry.domains() == ("orders", "users")

    def test_clear_empties_registry(self) -> None:
        """``clear`` удаляет все ресурсы."""
        registry = ExtensionResourceRegistry()
        registry.register(ExtensionResource("orders", "schema", "schema_in", int))

        registry.clear()

        assert registry.domains() == ()


class TestProcessWideRegistry:
    """Process-wide реестр и его связь с расширениями."""

    def test_register_extension_resource_helper(self) -> None:
        """Хелпер регистрации пишет в process-wide реестр."""
        register_extension_resource("orders", "schema", "schema_in", int)

        assert get_extension_resource("orders", "schema", "schema_in") is int

    def test_get_extension_resource_raises_for_unknown(self) -> None:
        """Неизвестный ресурс → ``KeyError`` (fail-fast, не «тихое None»)."""
        with pytest.raises(KeyError):
            get_extension_resource("no_such_domain", "schema", "nope")

    def test_real_extensions_are_registered(self) -> None:
        """Расширения проекта отдают свои ресурсы (динамическая загрузка)."""
        from src.backend.core.extension_registry import load_extension_resources

        load_extension_resources()
        domains = get_extension_registry().domains()

        assert "orders" in domains
        assert "users" in domains
        assert "files" in domains

    def test_order_service_is_resolvable(self) -> None:
        """Сервис заказов достаётся из реестра и остаётся callable."""
        service_getter = get_extension_resource("orders", "service", "orders")

        assert callable(service_getter)

    def test_user_model_is_resolvable(self) -> None:
        """ORM-модель пользователя достаётся из реестра."""
        model = get_extension_resource("users", "model", "user")

        assert getattr(model, "__name__", "") == "User"
