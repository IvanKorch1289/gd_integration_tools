"""W24 — factory.build_import_gateway для всех ImportSourceKind."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.interfaces.import_gateway import ImportSourceKind
from src.backend.infrastructure.import_gateway import build_import_gateway


@pytest.mark.parametrize("kind", list(ImportSourceKind))
def test_factory_constructs_gateway_for_each_kind(kind: ImportSourceKind) -> None:
    gateway = build_import_gateway(kind)
    assert gateway.kind is kind
    assert hasattr(gateway, "import_spec")
