"""Unit tests for S172 M3 ARC-006 — Extension DI infrastructure-module registry.

Тесты:

* Path validation (allowed prefixes, forbidden patterns).
* Registration lifecycle (register/unregister/clear/list).
* Idempotence (double-register = no-op).
* Thread safety (concurrent register).
* Resolver integration (resolve_module prefers extension over core).
* Public SDK facade (sdk/__init__.py exports work).

Notes:
    Тесты используют cleanup-фикстуру — каждый test сбрасывает
    registry для изоляции между тестами.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src.backend.core.di.module_registry import (
    ExtensionRegistrationError,
    ModuleRegistryError,
    clear_extension_modules,
    is_extension_path,
    list_extension_modules,
    register_extension_module,
    resolve_module,
    unregister_extension_module,
)


@pytest.fixture(autouse=True)
def _reset_extension_registry() -> None:
    """Per-test isolation: clear registry before AND after."""
    clear_extension_modules()
    yield
    clear_extension_modules()


class TestIsExtensionPath:
    """Tests for :func:`is_extension_path` (path validation)."""

    def test_valid_extension_path(self) -> None:
        assert is_extension_path("extensions.my_ext.infrastructure.foo")

    def test_valid_extension_path_with_underscore(self) -> None:
        assert is_extension_path(
            "extensions.skill_plugin.adapters.banking_metrics"
        )

    @pytest.mark.parametrize(
        "bad_path",
        [
            "src.backend.core.auth.api_key_backend",  # core
            "src.backend.infrastructure.cache",       # infrastructure
            "infrastructure.cache.rag",                # bare infra
            "core.ai.gateway",                          # bare core
            "my_extension.foo",                         # no prefix
            "extensions",                                # only prefix
            "extensions.",                               # trailing dot
            "extensions..double",                       # double dot
            "extensions.foo..bar",                       # double dot in middle
            "",                                           # empty
            "EXTENSIONS.FOO.BAR",                        # uppercase not allowed
            "extensions.foo-bar",                        # hyphen not allowed
        ],
    )
    def test_invalid_extension_paths(self, bad_path: str) -> None:
        assert is_extension_path(bad_path) is False

    def test_max_length_exceeded(self) -> None:
        long_path = "extensions." + "a" * 200
        assert is_extension_path(long_path) is False


class TestRegisterExtensionModule:
    """Tests for :func:`register_extension_module`."""

    def test_register_basic(self) -> None:
        assert register_extension_module(
            "my_ext.metrics",
            "extensions.my_ext.infrastructure.metrics",
        )
        assert list_extension_modules() == {
            "my_ext.metrics": "extensions.my_ext.infrastructure.metrics"
        }

    def test_register_returns_true_on_new(self) -> None:
        assert (
            register_extension_module(
                "k1", "extensions.k1.infra.foo"
            )
            is True
        )

    def test_register_idempotent_same_path(self) -> None:
        register_extension_module("k1", "extensions.k1.infra.foo")
        assert (
            register_extension_module("k1", "extensions.k1.infra.foo")
            is False
        )
        assert list_extension_modules() == {
            "k1": "extensions.k1.infra.foo"
        }

    def test_register_duplicate_with_different_path_raises(self) -> None:
        register_extension_module("k1", "extensions.k1.infra.foo")
        with pytest.raises(ExtensionRegistrationError, match="зарегистрирован"):
            register_extension_module("k1", "extensions.k1.infra.bar")

    @pytest.mark.parametrize(
        "bad_path",
        [
            "src.backend.x",
            "core.foo",
            "extensions.",      # empty after prefix
            "extensions..x",    # double dot
            "",
        ],
    )
    def test_register_rejects_invalid_path(self, bad_path: str) -> None:
        with pytest.raises(ExtensionRegistrationError):
            register_extension_module("k", bad_path)

    def test_register_non_str_path_raises(self) -> None:
        with pytest.raises(TypeError):
            register_extension_module("k", 123)  # type: ignore[arg-type]

    def test_register_empty_key_raises(self) -> None:
        with pytest.raises(TypeError):
            register_extension_module("", "extensions.x.y")


class TestUnregisterExtensionModule:
    """Tests for :func:`unregister_extension_module`."""

    def test_unregister_existing(self) -> None:
        register_extension_module("k1", "extensions.k1.infra.foo")
        assert unregister_extension_module("k1") is True
        assert "k1" not in list_extension_modules()

    def test_unregister_missing_returns_false(self) -> None:
        assert unregister_extension_module("missing") is False


class TestClearExtensionModules:
    """Tests for :func:`clear_extension_modules`."""

    def test_clear_returns_count(self) -> None:
        register_extension_module("k1", "extensions.k1.a")
        register_extension_module("k2", "extensions.k2.b")
        register_extension_module("k3", "extensions.k3.c")
        assert clear_extension_modules() == 3
        assert list_extension_modules() == {}

    def test_clear_empty_returns_zero(self) -> None:
        assert clear_extension_modules() == 0


class TestListExtensionModules:
    """Tests for :func:`list_extension_modules` (snapshot)."""

    def test_list_returns_copy(self) -> None:
        register_extension_module("k1", "extensions.k1.a")
        snapshot = list_extension_modules()
        snapshot["mutated"] = "extensions.x.y"  # type: ignore[index]
        assert "mutated" not in list_extension_modules()

    def test_list_empty(self) -> None:
        assert list_extension_modules() == {}


class TestResolveExtensionModule:
    """Tests that :func:`resolve_module` integrates extension-registry."""

    def test_resolve_extension_over_core(self) -> None:
        """Extension-registered key wins over core INFRA_MODULES.

        Mock ``import_module`` чтобы не нужен был реальный package.
        """
        register_extension_module(
            "clients.storage.redis",
            "extensions.overrides.dummy_redis",
        )

        sentinel = object()

        # Patch ``importlib.import_module`` чтобы вернуть sentinel
        # для нашего extension path. ``core.svcs_registry.resolve_module``
        # использует ``importlib.import_module`` (см. module_registry.py).
        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "extensions.overrides.dummy_redis":
                return sentinel
            # Возвращаем default error для всех остальных импортов.
            raise ImportError(f"unexpected import: {name}")

        with patch("importlib.import_module", side_effect=_fake_import):
            from src.backend.core.di import module_registry as _mr

            with patch.object(_mr, "importlib", wraps=__import__("importlib")):
                # Оборачиваем через прямой patch на import_module
                # внутри module_registry.
                with patch.object(_mr.importlib, "import_module", _fake_import):
                    # Расширенный ``INFRA_MODULES`` lookup должен
                    # пропустить key (т.к. он в extensions); иначе
                    # core импорт пройдёт → мы теряем проверку "extension wins".
                    # Чтобы обеспечить extension-wins: registry-extension содержит
                    # key ``clients.storage.redis`` → resolver должен
                    # попытаться import нашего extension path'а.
                    assert (
                        resolve_module("clients.storage.redis") is sentinel
                    )

    def test_resolve_unknown_key_raises(self) -> None:
        with pytest.raises(ModuleRegistryError):
            resolve_module("definitely.not.a.key")

    def test_resolve_extension_import_failure_wraps(self) -> None:
        """Если extension-модуль не import'ится — ModuleRegistryError."""
        register_extension_module(
            "definitely_missing.ext",
            "extensions.surely_does_not_exist.foo",
        )
        with pytest.raises(ModuleRegistryError, match="import failed"):
            resolve_module("definitely_missing.ext")


class TestThreadSafety:
    """Concurrent register из многих потоков — race-free."""

    def test_concurrent_registers_different_keys(self) -> None:
        """N потоков регистрируют разные ключи — все успешно."""

        def _register(idx: int) -> None:
            register_extension_module(
                f"key_{idx}", f"extensions.thread_{idx}.infra.foo"
            )

        threads = [
            threading.Thread(target=_register, args=(i,))
            for i in range(50)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = list_extension_modules()
        assert len(snap) == 50
        for i in range(50):
            assert f"key_{i}" in snap


class TestPublicSDKExport:
    """SDK facade в ``src.backend.sdk.__init__`` exposed API."""

    def test_sdk_exports_register_infra_module(self) -> None:
        from src.backend.sdk import register_infra_module
        assert callable(register_infra_module)

    def test_sdk_exports_unregister_infra_module(self) -> None:
        from src.backend.sdk import unregister_infra_module
        assert callable(unregister_infra_module)

    def test_sdk_exports_extension_registration_error(self) -> None:
        from src.backend.sdk import ExtensionRegistrationError as SDKError

        # Должна быть той же ошибкой, что и core.
        assert SDKError is ExtensionRegistrationError

    def test_sdk_exports_is_extension_path(self) -> None:
        from src.backend.sdk import is_extension_path

        assert is_extension_path is not None
        assert callable(is_extension_path)
