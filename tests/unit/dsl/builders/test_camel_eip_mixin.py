"""Unit-тесты ``CamelEIPMixin`` (dsl/builders/camel_eip.py).

Покрывают:
* модуль импортируется и предоставляет ``CamelEIPMixin``;
* ``CamelEIPMixin`` — mixin-класс с ``__slots__ = ()``;
* ``CamelEIPMixin`` может быть унаследован без конфликтов;
* mixin не вводит собственных dunder-методов, кроме ожидаемых Python'ом.

T-P0.1.20 — P0 v9 small worst-файл (3 stmts), цель coverage 80%+.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

from src.backend.dsl.builders.camel_eip import CamelEIPMixin


class TestModuleSurface:
    def test_mixin_is_importable(self) -> None:
        """``CamelEIPMixin`` доступен через ``src.backend.dsl.builders.camel_eip``."""
        assert CamelEIPMixin is not None
        assert isinstance(CamelEIPMixin, type)

    def test_mixin_has_docstring(self) -> None:
        """Класс имеет docstring — контракт mixin-документирован."""
        assert CamelEIPMixin.__doc__ is not None
        assert "EIP" in CamelEIPMixin.__doc__ or "миксин" in CamelEIPMixin.__doc__


class TestSlotsContract:
    def test_mixin_declares_empty_slots(self) -> None:
        """``CamelEIPMixin.__slots__ == ()`` — без собственных instance-полей."""
        assert CamelEIPMixin.__slots__ == ()

    def test_mixin_no_own_dunder_methods(self) -> None:
        """Mixin не объявляет собственных dunder-методов.

        Поведенческий mixin, ``__slots__ = ()`` — все атрибуты берутся
        из подкласса (RouteBuilder). Своих dunder добавлять не должен.
        """
        class_local: dict[str, Any] = CamelEIPMixin.__dict__
        own_dunder = {
            name
            for name in class_local
            if name.startswith("__") and name.endswith("__")
        }
        # ``__slots__``, ``__doc__``, ``__module__``, ``__qualname__`` ожидаемы;
        # ``__firstlineno__`` / ``__static_attributes__`` — Python 3.14+ auto-meta.
        # Никаких ``__init__`` / ``__getattr__`` / ``__iter__`` не должно быть.
        forbidden = own_dunder - {
            "__slots__",
            "__doc__",
            "__module__",
            "__qualname__",
            "__firstlineno__",
            "__static_attributes__",
        }
        assert forbidden == set(), (
            f"Unexpected dunder methods in CamelEIPMixin: {forbidden}"
        )


class TestInheritance:
    def test_can_be_used_as_mixin(self) -> None:
        """``CamelEIPMixin`` корректно миксуется в произвольный класс."""

        class _Host:
            """Заглушка-host для проверки наследования mixin."""

            attr: str = "host-value"

        class _Mixed(_Host, CamelEIPMixin):
            pass

        instance = _Mixed()
        # Собственные атрибуты host-класса доступны.
        assert instance.attr == "host-value"
        # mixin не сломал isinstance-цепочку.
        assert isinstance(instance, _Mixed)
        assert isinstance(instance, CamelEIPMixin)
        assert isinstance(instance, _Host)

    def test_mixin_does_not_add_init_args(self) -> None:
        """``CamelEIPMixin`` не имеет ``__init__`` — subclass-init работает штатно."""

        class _WithInit(CamelEIPMixin):
            def __init__(self, value: int) -> None:
                self.value = value

        instance = _WithInit(value=42)
        assert instance.value == 42

    def test_mixin_does_not_impose_required_attributes(self) -> None:
        """``__slots__ = ()`` не требует от subclass обязательных полей.

        Проверяем через ``hasattr`` — mixin не должен «зашивать»
        какие-либо обязательные атрибуты в ``__slots__``.
        """

        class _Empty(CamelEIPMixin):
            pass

        instance = _Empty()
        # Создание объекта без аргументов не падает.
        assert instance is not None


class TestModuleImportSideEffects:
    """Smoke-тест: модуль импортируется без side-effects и регистраций."""

    def test_import_does_not_register_processors(self) -> None:
        """Импорт mixin-модуля не должен регистрировать новые процессоры.

        ``CamelEIPMixin`` — поведенческий mixin (``Stateless``), в реестр
        процессоров ничего не добавляется. Это проверяем через
        стабильность ``ProcessorRegistry._by_fqn`` до/после импорта.
        """
        from src.backend.dsl.registry import get_processor_registry

        registry = get_processor_registry()
        before = set(registry._by_fqn)
        # Re-import безопасен: тестируем именно side-effect-free.
        import importlib

        import src.backend.dsl.builders.camel_eip as camel_eip_mod

        importlib.reload(camel_eip_mod)
        after = set(registry._by_fqn)
        assert before == after, (
            "Reloading camel_eip не должно менять ProcessorRegistry"
        )
