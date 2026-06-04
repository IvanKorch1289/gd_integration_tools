"""Tests for src.backend.core.config.source_spec."""

from __future__ import annotations

import pytest

from src.backend.core.config.source_spec import SourceSpec, SourcesSpecFile
from src.backend.core.interfaces.invoker import InvocationMode
from src.backend.core.interfaces.source import SourceKind


class TestSourceSpec:
    def test_defaults(self) -> None:
        s = SourceSpec(id="s1", kind=SourceKind.WEBHOOK, action="a1")
        assert s.mode == InvocationMode.SYNC
        assert s.idempotency is True
        assert s.config == {}

    def test_validation_missing_id(self) -> None:
        with pytest.raises(Exception):
            SourceSpec(id="", kind=SourceKind.WEBHOOK, action="a1")


class TestSourcesSpecFile:
    def test_defaults(self) -> None:
        f = SourcesSpecFile()
        assert f.sources == []
