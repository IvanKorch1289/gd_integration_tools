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


class TestConcurrentLoad:
    """Гонка первых обращений (ADR-0457): загрузка расширений — общая для процесса."""

    @pytest.mark.unit
    def test_parallel_first_access_does_not_raise_keyerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Параллельные потоки дожидаются загрузки, а не получают KeyError.

        Регрессия: ``load_extension_resources`` при активной загрузке в
        другом потоке делал ``return`` немедленно — потребитель тут же
        обращался к полузагруженному реестру и получал ``KeyError``
        (спорадические 500 на первых запросах после старта).
        """
        import threading
        import time

        import src.backend.core.extension_registry as registry

        started = threading.Event()
        results: list[object] = []
        errors: list[BaseException] = []

        def _fake_discover(package_name: str, *, depth: int) -> None:
            started.set()
            time.sleep(0.3)  # имитация тяжёлого импорта расширений
            registry.register_extension_resource("race", "schema", "s", int)

        monkeypatch.setattr(registry, "_discover_package", _fake_discover)

        def _worker() -> None:
            try:
                results.append(registry.get_extension_resource("race", "schema", "s"))
            except BaseException as exc:  # noqa: BLE001 — тест фиксирует отказ
                errors.append(exc)

        loader = threading.Thread(target=_worker)
        loader.start()
        assert started.wait(timeout=5), "загрузка расширений не стартовала"

        waiters = [threading.Thread(target=_worker) for _ in range(3)]
        for thread in waiters:
            thread.start()
        loader.join(timeout=30)
        for thread in waiters:
            thread.join(timeout=30)

        assert errors == []
        assert results == [int, int, int, int]

    @pytest.mark.unit
    def test_reset_drops_registered_resources(self) -> None:
        """``reset_extension_resources`` очищает реестр (изоляция тестов)."""
        register_extension_resource("orders", "schema", "schema_in", int)

        reset_extension_resources()

        assert get_extension_registry().find("orders", "schema", "schema_in") is None

    @pytest.mark.unit
    def test_resource_registered_as_none_is_not_missing(self) -> None:
        """Ресурс, зарегистрированный как ``None``, — не «отсутствующий»."""
        register_extension_resource("orders", "schema", "maybe", None)

        assert get_extension_resource("orders", "schema", "maybe") is None

    @pytest.mark.unit
    def test_keyerror_reports_extension_load_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KeyError потребителя содержит реальную причину (сломанное расширение).

        Регрессия: ошибка импорта расширения глушилась warning-логом, а
        потребитель получал ``KeyError`` с текстом «проверь, что расширение
        экспортирует модуль resources» — без указания настоящей причины.
        """
        import src.backend.core.extension_registry as registry

        class _FakeImportlib:
            """Подмена ``importlib`` в модуле реестра (глобальный не трогаем)."""

            util = registry.importlib.util

            @staticmethod
            def import_module(name: str) -> object:
                raise ModuleNotFoundError(
                    "No module named 'broken_dependency'", name="broken_dependency"
                )

        def _fake_discover(package_name: str, *, depth: int) -> None:
            registry._load_extension("extensions.broken", depth=depth)

        monkeypatch.setattr(registry, "importlib", _FakeImportlib)
        monkeypatch.setattr(registry, "_discover_package", _fake_discover)

        with pytest.raises(KeyError) as exc:
            get_extension_resource("broken", "schema", "nope")

        message = str(exc.value)
        assert "broken_dependency" in message
        assert "extensions.broken.resources" in message
