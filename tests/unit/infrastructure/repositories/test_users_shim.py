"""Unit tests for backward-compat shim users.py.

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
class TestUsersShim:
    @pytest.fixture(autouse=True)
    def _patch_extensions(self) -> None:
        fake_mod = ModuleType("extensions.core_entities.users.repositories.users")
        fake_mod.UserRepository = MagicMock(name="UserRepository")
        fake_mod.get_user_repo = MagicMock(name="get_user_repo")
        sys.modules["extensions.core_entities.users.repositories.users"] = fake_mod
        sys.modules.pop("src.backend.infrastructure.repositories.users", None)
        yield
        sys.modules.pop("extensions.core_entities.users.repositories.users", None)
        sys.modules.pop("src.backend.infrastructure.repositories.users", None)

    def test_import_emits_deprecation_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module("src.backend.infrastructure.repositories.users")

        relevant = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "src.backend.infrastructure.repositories.users устарел" in str(x.message)
        ]
        assert relevant, "expected DeprecationWarning from backward-compat shim"

    def test_all_exports(self) -> None:
        mod = importlib.import_module("src.backend.infrastructure.repositories.users")
        assert set(mod.__all__) == {"UserRepository", "get_user_repo"}

    def test_reexports_match_upstream(self) -> None:
        mod = importlib.import_module("src.backend.infrastructure.repositories.users")
        upstream = sys.modules["extensions.core_entities.users.repositories.users"]
        assert mod.UserRepository is upstream.UserRepository
        assert mod.get_user_repo is upstream.get_user_repo
