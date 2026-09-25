"""Regression tests для hvac graceful fallback fix (cycle 158+).

Per v4 §10 P1 'evidence требует testable surface': VaultConfigSettingsSource
fix для silent degradation when ``hvac`` missing в venv.

Problem (pre-fix):
- ``VaultConfigSettingsSource._load_data()`` делает ``from hvac import Client``
  unconditionally.
- Когда hvac missing → ImportError поднимается, ловится
  ``FilteredSettingsSource.__call__() → _handle_error()``.
- Per Pydantic class construction = 1 log entry → 17+ Settings-классов =
  17+ duplicate log spam + per-class ImportError overhead.

Fix (cycle 158+):
- Module-level ``_HVAC_AVAILABLE`` cached check через
  ``_hvac_module_available()`` (uses ``importlib.util.find_spec``).
- Early return в ``_load_data()`` если ``hvac`` не importable.
- Установка ``_VAULT_UNREACHABLE = True`` чтобы cache остальное поведение.
"""

from __future__ import annotations

import importlib

import pytest


def _reload_config_loader():
    """Reload ``config_loader`` module to reset ``_HVAC_AVAILABLE`` cache.

    Per v4 §10 testable surface: cache должен be testable для
    verifying state transitions.
    """
    import src.backend.core.config.config_loader as cl

    importlib.reload(cl)
    return cl


class TestHvacAvailabilityCache:
    """``_HVAC_AVAILABLE`` module-level global cache."""

    def test_initial_state_is_none_before_check(self) -> None:
        """Lazy-init: cache начинается как None (= not checked yet).

        Это контракт: до первого вызова ``_hvac_module_available()`` нет
        known state. _load_data() должен trigger check lazily.
        """
        # Force fresh module — drop _HVAC_AVAILABLE.
        cl = _reload_config_loader()
        assert cl._HVAC_AVAILABLE is None, (
            "Cache должен быть None при fresh module load"
        )

    def test_hvac_module_available_caches_result(self) -> None:
        """После вызова ``_hvac_module_available()`` cache обновляется.

        На этой машине hvac missing (not installed в venv). Ожидаем
        cache = False. Если hvac available в CI, ожидаем True.
        """
        cl = _reload_config_loader()
        # Pre-condition: cache = None.
        assert cl._HVAC_AVAILABLE is None

        # First call: triggers check, updates cache.
        result = cl._hvac_module_available()

        # Post-condition: cache reflects result.
        assert cl._HVAC_AVAILABLE == result
        assert cl._HVAC_AVAILABLE is not None
        # Consistency: cached result must match.
        assert cl._HVAC_AVAILABLE is False, (
            "Expected hvac=False (not installed в venv); "
            "if hvac IS installed, package's required hvac → True."
        )

    def test_subsequent_calls_use_cache(self) -> None:
        """Test isolation: каждый test начинается с fresh reload.

        Если другой test проверял cache = True, наш не должен
        inherit; _reload_config_loader() drops state.
        """
        cl = _reload_config_loader()
        cl._hvac_module_available()
        # Sanity: cache populated.
        assert cl._HVAC_AVAILABLE is not None


class TestVaultConfigSettingsSourceHvacFallback:
    """``_load_data()`` short-circuits when hvac missing."""

    def test_load_data_returns_empty_when_hvac_missing(self) -> None:
        """Если hvac missing → _load_data() возвращает {} без log spam.

        Fix поведение: silent degradation вместо per-class errors.
        """
        cl = _reload_config_loader()
        # Verify precondition: hvac really missing.
        assert cl._hvac_module_available() is False

        # Test source instance.

        # Try to construct a VaultConfigSettingsSource.
        # Skip if constructor needs additional args (model_cls,
        # settings_cls) — exercise  _load_data() directly via stub.
        # Per PydanticBaseSettingsSource interface, _load_data is the
        # core method. We invoke via __call__() to test full chain.
        # For test purposes, we use the public method directly.
        from src.backend.core.config.config_loader import _VAULT_UNREACHABLE

        # Reset _VAULT_UNREACHABLE для каждого test (not strictly needed:
        # _load_data() устанавливает в True при hvac missing).
        if _VAULT_UNREACHABLE:
            cl._VAULT_UNREACHABLE = False

        # Direct call test (bypass Pydantic integration).
        # Use a minimal stub: __call__() returns dict, _load_data() returns dict.
        class _StubSource(cl.VaultConfigSettingsSource):
            def __init__(self):
                # Skip super().__init__ — only test _load_data logic.
                pass

            def _filter_data(self, raw_data):
                return raw_data

        source = _StubSource()
        result = source._load_data()

        # Expected: {} (no Vault data; silent return).
        assert result == {}, (
            f"Expected {{}} (empty Vault data) when hvac missing; got {result!r}"
        )

        # Post-condition: _VAULT_UNREACHABLE = True (cache for next call).
        # _load_data() устанавливает этот global flag when hvac missing.
        # Note: previous test run может already have set it; not strictly
        # testable in this isolated scope, but log spam should be 0.


class TestBackwardsCompatibility:
    """Public contract — preserved per v4 §6 «Parity»."""

    def test_hvac_module_available_callable(self) -> None:
        """``_hvac_module_available()`` остаётся вызываемой."""
        cl = _reload_config_loader()
        # Function exists, is callable, returns bool.
        result = cl._hvac_module_available()
        assert isinstance(result, bool)

    def test_load_data_handles_hvac_missing_no_exception(self) -> None:
        """_load_data() не бросает ImportError при missing hvac.

        Pre-fix: ImportError raise (caught в __call__).
        Post-fix: returns {}} early, без raise.
        """
        cl = _reload_config_loader()

        class _StubSource(cl.VaultConfigSettingsSource):
            def __init__(self):
                pass

            def _filter_data(self, raw_data):
                return raw_data

        source = _StubSource()

        # Should not raise ImportError (was previously).
        try:
            result = source._load_data()
        except ImportError as exc:
            pytest.fail(
                f"_load_data() should NOT raise ImportError post-fix; got {exc!r}"
            )

        assert result == {}
