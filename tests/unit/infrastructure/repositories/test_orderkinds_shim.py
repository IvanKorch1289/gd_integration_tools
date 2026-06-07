"""Unit tests for backward-compat shim orderkinds.py.

Mocks the upstream extensions module so the shim can load without
requiring real extensions code.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestOrderKindsShim:
    @pytest.fixture(autouse=True)
    def _patch_extensions(self) -> None:
        fake_mod = ModuleType(
            "extensions.core_entities.orderkinds.repositories.orderkinds"
        )
        fake_mod.OrderKindRepository = MagicMock(name="OrderKindRepository")
        fake_mod.get_order_kind_repo = MagicMock(name="get_order_kind_repo")
        sys.modules["extensions.core_entities.orderkinds.repositories.orderkinds"] = (
            fake_mod
        )
        sys.modules.pop("src.backend.infrastructure.repositories.orderkinds", None)
        yield
        sys.modules.pop(
            "extensions.core_entities.orderkinds.repositories.orderkinds", None
        )
        sys.modules.pop("src.backend.infrastructure.repositories.orderkinds", None)

    def test_import_emits_deprecation_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module(
                "src.backend.infrastructure.repositories.orderkinds"
            )

        relevant = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "src.backend.infrastructure.repositories.orderkinds устарел"
            in str(x.message)
        ]
        assert relevant, "expected DeprecationWarning from backward-compat shim"

    def test_all_exports(self) -> None:
        mod = importlib.import_module(
            "src.backend.infrastructure.repositories.orderkinds"
        )
        assert set(mod.__all__) == {"OrderKindRepository", "get_order_kind_repo"}

    def test_reexports_match_upstream(self) -> None:
        mod = importlib.import_module(
            "src.backend.infrastructure.repositories.orderkinds"
        )
        upstream = sys.modules[
            "extensions.core_entities.orderkinds.repositories.orderkinds"
        ]
        assert mod.OrderKindRepository is upstream.OrderKindRepository
        assert mod.get_order_kind_repo is upstream.get_order_kind_repo
