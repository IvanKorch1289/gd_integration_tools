"""Unit tests for dsl.builders.__init__ lazy imports."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

import src.backend.dsl.builders as builders_mod


def test_lazy_route_builder() -> None:
    rb = builders_mod.RouteBuilder
    assert rb is not None


def test_lazy_core_mixin() -> None:
    mixin = builders_mod.CoreMixin
    assert mixin.__name__ == "CoreMixin"
    assert issubclass(mixin, builders_mod.RouteBuilder)


def test_lazy_transport_mixin() -> None:
    mixin = builders_mod.TransportMixin
    assert mixin.__name__ == "TransportMixin"


def test_lazy_eip_mixin() -> None:
    mixin = builders_mod.EIPMixin
    assert mixin.__name__ == "EIPMixin"


def test_lazy_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError, match="has no attribute"):
        _ = builders_mod.NonExistent
