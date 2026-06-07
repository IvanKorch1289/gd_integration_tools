"""Unit tests for backward-compat shim files.py.

The shim re-exports ``FileRepository`` and ``get_file_repo`` from
``extensions.core_entities.files.repositories.files`` and emits a
DeprecationWarning on import. We mock the upstream extensions module
so the test stays isolated and does not depend on extensions code.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
class TestFilesShim:
    @pytest.fixture(autouse=True)
    def _patch_extensions(self) -> None:
        """Inject a fake extensions module so the shim can import it."""
        fake_mod = ModuleType("extensions.core_entities.files.repositories.files")
        fake_mod.FileRepository = MagicMock(name="FileRepository")
        fake_mod.get_file_repo = MagicMock(name="get_file_repo")
        sys.modules["extensions.core_entities.files.repositories.files"] = fake_mod
        # Remove cached shim to force a fresh import for each test.
        sys.modules.pop("src.backend.infrastructure.repositories.files", None)
        yield
        sys.modules.pop("extensions.core_entities.files.repositories.files", None)
        sys.modules.pop("src.backend.infrastructure.repositories.files", None)

    def test_import_emits_deprecation_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module("src.backend.infrastructure.repositories.files")

        relevant = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "src.backend.infrastructure.repositories.files устарел"
            in str(x.message)
        ]
        assert relevant, "expected DeprecationWarning from backward-compat shim"

    def test_all_exports(self) -> None:
        mod = importlib.import_module("src.backend.infrastructure.repositories.files")
        assert set(mod.__all__) == {"FileRepository", "get_file_repo"}

    def test_reexports_match_upstream(self) -> None:
        mod = importlib.import_module("src.backend.infrastructure.repositories.files")
        upstream = sys.modules["extensions.core_entities.files.repositories.files"]
        assert mod.FileRepository is upstream.FileRepository
        assert mod.get_file_repo is upstream.get_file_repo
