"""Tests for langmem/backends.py (cycle 69).

Stream E.7 — advanced-alchemy backend wrappers для LangMem.

Critical for memory layer integrity:
- AdvancedAlchemyMissing error path
- get_episodic_repository / get_procedural_repository factories
- model_type binding to LangMemEpisodic / LangMemProcedural
- _resolve_repository_cls error handling

Cycle 69 invariant: tests catch regressions in memory backend
factories that could lead to silent model_type mismatches.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestAdvancedAlchemyMissing:
    """AdvancedAlchemyMissing — exception raised when advanced-alchemy not installed."""

    def test_is_runtime_error_subclass(self) -> None:
        """AdvancedAlchemyMissing is a RuntimeError subclass."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
        )

        assert issubclass(AdvancedAlchemyMissing, RuntimeError)

    def test_can_be_raised_with_message(self) -> None:
        """AdvancedAlchemyMissing can be raised and caught with a message."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
        )

        with pytest.raises(AdvancedAlchemyMissing, match="advanced-alchemy"):
            raise AdvancedAlchemyMissing("advanced-alchemy not installed")

    def test_raised_with_chain(self) -> None:
        """AdvancedAlchemyMissing preserves exception chain (raise from exc)."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
        )

        original = ImportError("No module named 'advanced_alchemy'")
        try:
            try:
                raise original
            except ImportError as exc:
                raise AdvancedAlchemyMissing("test") from exc
        except AdvancedAlchemyMissing as aae:
            assert aae.__cause__ is original, "Should preserve __cause__ chain"


class TestResolveRepositoryCls:
    """_resolve_repository_cls — lazy import helper."""

    def test_raises_advanced_alchemy_missing_when_missing(self) -> None:
        """When advanced_alchemy NOT installed → raises AdvancedAlchemyMissing.

        Cycle 69 invariant: function is robust to missing dep.
        Test uses import-blocked patch to simulate missing dep.
        """
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            _resolve_repository_cls,
        )

        # Patch the import to raise ImportError for advanced_alchemy.
        with patch.dict("sys.modules", {"advanced_alchemy.repository": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'advanced_alchemy.repository'"),
            ):
                with pytest.raises(AdvancedAlchemyMissing, match="advanced-alchemy"):
                    _resolve_repository_cls()

    def test_raises_when_advanced_alchemy_missing_in_real_env(self) -> None:
        """In dev_light (no advanced_alchemy) → raises AdvancedAlchemyMissing.

        Cycle 69 invariant: real environment also tested. If
        advanced_alchemy is genuinely missing (current test env),
        function raises with helpful message about 'uv sync'.
        """
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            _resolve_repository_cls,
        )

        # Only meaningful if advanced_alchemy is not installed.
        try:
            import advanced_alchemy.repository  # noqa: F401
            pytest.skip("advanced_alchemy is installed in this env")
        except ImportError:
            with pytest.raises(AdvancedAlchemyMissing, match="advanced-alchemy"):
                _resolve_repository_cls()


class TestGetEpisodicRepository:
    """get_episodic_repository factory."""

    def test_propagates_import_error(self) -> None:
        """get_episodic_repository raises AdvancedAlchemyMissing if no advanced_alchemy."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            get_episodic_repository,
        )

        with patch.dict("sys.modules", {"advanced_alchemy.repository": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'advanced_alchemy.repository'"),
            ):
                with pytest.raises(AdvancedAlchemyMissing):
                    get_episodic_repository(MagicMock())

    def test_raises_in_real_env_without_advanced_alchemy(self) -> None:
        """Real dev_light env (no advanced_alchemy) → AdvancedAlchemyMissing."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            get_episodic_repository,
        )

        try:
            import advanced_alchemy.repository  # noqa: F401
            pytest.skip("advanced_alchemy installed")
        except ImportError:
            with pytest.raises(AdvancedAlchemyMissing):
                get_episodic_repository(MagicMock())

    def test_model_type_binding_episodic(self) -> None:
        """When advanced_alchemy is available, model_type binds to LangMemEpisodic."""
        from src.backend.core.domain.models.langmem_models import LangMemEpisodic
        from src.backend.services.ai.memory.langmem.backends import (
            get_episodic_repository,
        )

        try:
            import advanced_alchemy.repository  # noqa: F401
        except ImportError:
            pytest.skip("advanced_alchemy not installed")

        session = MagicMock()
        result = get_episodic_repository(session)
        assert result.model_type is LangMemEpisodic


class TestGetProceduralRepository:
    """get_procedural_repository factory."""

    def test_propagates_import_error(self) -> None:
        """get_procedural_repository raises AdvancedAlchemyMissing if no advanced_alchemy."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            get_procedural_repository,
        )

        with patch.dict("sys.modules", {"advanced_alchemy.repository": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'advanced_alchemy.repository'"),
            ):
                with pytest.raises(AdvancedAlchemyMissing):
                    get_procedural_repository(MagicMock())

    def test_raises_in_real_env_without_advanced_alchemy(self) -> None:
        """Real dev_light env (no advanced_alchemy) → AdvancedAlchemyMissing."""
        from src.backend.services.ai.memory.langmem.backends import (
            AdvancedAlchemyMissing,
            get_procedural_repository,
        )

        try:
            import advanced_alchemy.repository  # noqa: F401
            pytest.skip("advanced_alchemy installed")
        except ImportError:
            with pytest.raises(AdvancedAlchemyMissing):
                get_procedural_repository(MagicMock())

    def test_model_type_binding_procedural(self) -> None:
        """When advanced_alchemy is available, model_type binds to LangMemProcedural."""
        from src.backend.core.domain.models.langmem_models import LangMemProcedural
        from src.backend.services.ai.memory.langmem.backends import (
            get_procedural_repository,
        )

        try:
            import advanced_alchemy.repository  # noqa: F401
        except ImportError:
            pytest.skip("advanced_alchemy not installed")

        session = MagicMock()
        result = get_procedural_repository(session)
        assert result.model_type is LangMemProcedural


class TestModuleContract:
    """Module-level invariants для langmem.backends."""

    def test_all_exports(self) -> None:
        """__all__ contains expected public API."""
        from src.backend.services.ai.memory.langmem import backends

        assert "AdvancedAlchemyMissing" in backends.__all__
        assert "get_episodic_repository" in backends.__all__
        assert "get_procedural_repository" in backends.__all__
        # _resolve_repository_cls is private (not in __all__).
        assert "_resolve_repository_cls" not in backends.__all__
