"""P1-6 (cycle 241): regression tests for facade promotion.

Validates that the 11 newly promoted base classes are accessible
via ``from src.backend.core.api import X`` and resolve to the same
identity as the original ``from src.backend.core.Y import X`` path.

This prevents accidental breakage of extension authors who migrate
to the facade.
"""

from __future__ import annotations

import pytest


# P1-6 promoted symbols: (facade_name, original_module, original_name)
PROMOTED: list[tuple[str, str, str]] = [
    ("BasePlugin", "src.backend.core.interfaces.plugin", "BasePlugin"),
    ("BaseModel", "src.backend.core.domain.models.base", "BaseModel"),
    ("nullable_str", "src.backend.core.domain.models.base", "nullable_str"),
    ("BaseSchema", "src.backend.schemas.base", "BaseSchema"),
    ("BaseService", "src.backend.services.core.base", "BaseService"),
    ("SQLAlchemyRepository", "src.backend.core.repositories.base", "SQLAlchemyRepository"),
    ("TenantMixin", "src.backend.core.tenancy.sqlalchemy_filter", "TenantMixin"),
    ("main_session_manager", "src.backend.core.database.session", "main_session_manager"),
    ("load_plugin_manifest", "src.backend.core.plugin_runtime.manifest", "load_plugin_manifest"),
    ("RetryPolicy", "src.backend.core.ai.retry_policy", "RetryPolicy"),
    ("validate_inn", "src.backend.dsl.helpers.banking", "validate_inn"),
    ("get_feature_flag_service", "src.backend.core.feature_flags", "get_feature_flag_service"),
]


@pytest.mark.parametrize("facade_name, original_module, original_name", PROMOTED)
def test_facade_promoted_symbol_resolves(facade_name: str, original_module: str, original_name: str) -> None:
    """Promoted symbol доступен через core.api facade и identical к original."""
    import importlib

    facade = importlib.import_module("src.backend.core.api")
    from_api = getattr(facade, facade_name)
    assert from_api is not None, f"{facade_name} returned None from facade"

    # Verify identity — facade must re-export same object as original module
    original = importlib.import_module(original_module)
    from_original = getattr(original, original_name)
    assert from_api is from_original, (
        f"Facade {facade_name} is NOT identical to {original_module}.{original_name}: "
        f"facade={from_api!r} original={from_original!r}"
    )


def test_facade_all_contains_promoted_symbols() -> None:
    """Все promoted symbols в __all__ для статического анализа."""
    import src.backend.core.api as api_mod

    for facade_name, _, _ in PROMOTED:
        assert facade_name in api_mod.__all__, (
            f"{facade_name} отсутствует в core.api.__all__ "
            f"(breaks static analysis + IDE autocomplete)"
        )


def test_facade_dir_contains_promoted_symbols() -> None:
    """__dir__() возвращает promoted symbols для tab-completion."""
    import src.backend.core.api as api_mod

    listed = set(api_mod.__dir__())
    for facade_name, _, _ in PROMOTED:
        assert facade_name in listed, (
            f"{facade_name} отсутствует в core.api.__dir__() (breaks tab-completion)"
        )


def test_facade_unknown_attribute_raises_attribute_error() -> None:
    """Unknown name → AttributeError (НЕ silent None / NOT ImportError)."""
    import src.backend.core.api as api_mod

    with pytest.raises(AttributeError) as exc_info:
        api_mod.__getattr__("NonExistentSymbol_xyz")
    assert "NonExistentSymbol_xyz" in str(exc_info.value)
