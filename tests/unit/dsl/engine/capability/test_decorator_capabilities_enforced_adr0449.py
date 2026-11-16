"""ADR-0449 — capability из декларации процессора проверяется в рантайме.

Контекст
--------
``@processor(capabilities=(...))`` публиковал capability в JSON-схеме, но
движок её не проверял — 44 декларации были декоративными (allowlist гейта).
Теперь capability, чьё имя есть в vocabulary, проверяется как обычная
runtime-декларация; имена вне vocabulary остаются advisory.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities.vocabulary import build_default_vocabulary
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit


def test_vocabulary_contains_net_outbound() -> None:
    """В vocabulary есть capability, которую используют процессоры."""
    names = {d.name for d in build_default_vocabulary().all()}
    assert "net.outbound" in names


def test_decorator_capability_in_vocabulary_is_enforced() -> None:
    """Capability из декларации (имя есть в vocabulary) попадает в проверку."""
    from src.backend.dsl.registry.processor import processor

    @processor("test.proc", capabilities=("net.outbound:external",))
    class _Proc(BaseProcessor):
        """Процессор с декларацией capability."""

        async def process(self, exchange: Any, context: Any) -> None:
            """Холостой процессор."""

    declared = _Proc()._declared_capabilities()
    assert "net.outbound" in declared


def test_unknown_capability_name_stays_advisory() -> None:
    """Имя вне vocabulary остаётся advisory (не блокирует вызов)."""
    from src.backend.dsl.registry.processor import processor

    @processor("test.proc2", capabilities=("net.outbound.not.in.vocabulary:external",))
    class _Proc(BaseProcessor):
        """Процессор с нестандартной capability-формой."""

        async def process(self, exchange: Any, context: Any) -> None:
            """Холостой процессор."""

    assert "net.outbound.not.in.vocabulary" not in _Proc()._declared_capabilities()


def test_required_capability_kept_first() -> None:
    """``required_capability`` проверяется первой (совместимость контракта)."""

    class _Proc(BaseProcessor):
        """Процессор с одиночной capability."""

        required_capability = "storage.read"

        async def process(self, exchange: Any, context: Any) -> None:
            """Холостой процессор."""

    assert _Proc()._declared_capabilities()[0] == "storage.read"
