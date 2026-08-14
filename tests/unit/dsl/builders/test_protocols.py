"""Regression tests for RouteBuilder MRO Protocols catalog (2026-08-14).

Verifies:
1. ``__all__`` exports exactly 8 Protocol classes + 3 helpers.
2. ``_CATEGORY_MAP`` covers exactly 36 top-level mixins.
3. All 8 categories are distinct.
4. ``get_category_for_mixin`` resolves known mixins; returns None for unknown.
5. ``get_protocol_for_category`` resolves category names; returns None for unknown.
6. ``is_runtime_protocol_conformant`` returns True for ALL 8 categories on a
   real ``RouteBuilder()`` instance (proves category-map is in sync with MRO).
7. ``is_runtime_protocol_conformant`` returns False for unknown category name.

Если какой-то mixin будет удалён/добавлен в ``RouteBuilder.__bases__`` без
обновления ``_CATEGORY_MAP`` — conformance check упадёт, и разработчик
получит явный сигнал пересмотреть ``protocols.py``.
"""

from __future__ import annotations


def test_protocols_module_exports() -> None:
    """8 Protocol classes + 3 helper functions в ``__all__``."""
    from src.backend.dsl.builders import protocols

    assert hasattr(protocols, "__all__")
    exported = set(protocols.__all__)
    expected_classes = {
        "AIAgentProtocol",
        "ControlFlowProtocol",
        "DataStoreProtocol",
        "EIPProtocol",
        "InfrastructureProtocol",
        "MessagingProtocol",
        "ResilienceProtocol",
        "TransportProtocol",
    }
    expected_helpers = {
        "get_category_for_mixin",
        "get_protocol_for_category",
        "is_runtime_protocol_conformant",
    }
    assert expected_classes.issubset(exported), (
        f"Missing Protocols in __all__: {expected_classes - exported}"
    )
    assert expected_helpers.issubset(exported), (
        f"Missing helpers in __all__: {expected_helpers - exported}"
    )


def test_category_map_covers_36_mixins() -> None:
    """``_CATEGORY_MAP`` имеет ровно 36 записей (по одной на каждый top-level mixin)."""
    from src.backend.dsl.builders import protocols

    assert len(protocols._CATEGORY_MAP) == 36, (
        f"Expected 36 mixins in _CATEGORY_MAP, got {len(protocols._CATEGORY_MAP)} — "
        "обновите map при изменении RouteBuilder.__bases__"
    )


def test_eight_distinct_categories() -> None:
    """В ``_CATEGORY_MAP`` должно быть ровно 8 различных Protocol-классов."""
    from src.backend.dsl.builders import protocols

    categories = set(protocols._CATEGORY_MAP.values())
    assert len(categories) == 8, (
        f"Expected 8 distinct categories, got {len(categories)}: {categories}"
    )


def test_get_category_for_mixin_known() -> None:
    """``get_category_for_mixin`` возвращает правильный Protocol для known mixin'ов."""
    from src.backend.dsl.builders.protocols import (
        AIAgentProtocol,
        ControlFlowProtocol,
        EIPProtocol,
        MessagingProtocol,
        ResilienceProtocol,
        TransportProtocol,
        get_category_for_mixin,
    )

    assert get_category_for_mixin("EIPMixin") is EIPProtocol
    assert get_category_for_mixin("ControlFlowMixin") is ControlFlowProtocol
    assert get_category_for_mixin("AIRPAMixin") is AIAgentProtocol
    assert get_category_for_mixin("TransportSourcesMixin") is TransportProtocol
    assert get_category_for_mixin("ComplianceMixin") is ResilienceProtocol
    assert get_category_for_mixin("EventBusMixin") is MessagingProtocol


def test_get_category_for_mixin_unknown_returns_none() -> None:
    """``get_category_for_mixin`` возвращает None для неизвестного mixin'а."""
    from src.backend.dsl.builders.protocols import get_category_for_mixin

    assert get_category_for_mixin("NonExistentMixin") is None
    assert get_category_for_mixin("") is None


def test_get_protocol_for_category_known() -> None:
    """``get_protocol_for_category`` резолвит category-name → Protocol-класс."""
    from src.backend.dsl.builders.protocols import (
        AIAgentProtocol,
        ControlFlowProtocol,
        DataStoreProtocol,
        EIPProtocol,
        get_protocol_for_category,
    )

    assert get_protocol_for_category("ControlFlow") is ControlFlowProtocol
    assert get_protocol_for_category("EIP") is EIPProtocol
    assert get_protocol_for_category("AIAgent") is AIAgentProtocol
    assert get_protocol_for_category("DataStore") is DataStoreProtocol


def test_get_protocol_for_category_unknown_returns_none() -> None:
    """``get_protocol_for_category`` возвращает None для неизвестной категории."""
    from src.backend.dsl.builders.protocols import get_protocol_for_category

    assert get_protocol_for_category("Unknown") is None
    assert get_protocol_for_category("not_a_category") is None


def test_route_builder_conformant_all_8_categories() -> None:
    """Реальный ``RouteBuilder()`` удовлетворяет ВСЕМ 8 категориям.

    Если кто-то добавит mixin в ``RouteBuilder.__bases__`` без
    обновления ``_CATEGORY_MAP`` — этот тест упадёт.
    """
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.builders.protocols import is_runtime_protocol_conformant

    rb = RouteBuilder("test.protocols_conformance", source="timer:60s")
    categories = [
        "ControlFlow", "EIP", "DataStore", "Transport",
        "Infrastructure", "Resilience", "AIAgent", "Messaging",
    ]
    for cat in categories:
        assert is_runtime_protocol_conformant(rb, cat), (
            f"RouteBuilder не соответствует категории '{cat}'. "
            "Проверьте _CATEGORY_MAP в src/backend/dsl/builders/protocols.py."
        )


def test_is_runtime_protocol_conformant_unknown_returns_false() -> None:
    """``is_runtime_protocol_conformant`` возвращает False для неизвестной категории."""
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.builders.protocols import is_runtime_protocol_conformant

    rb = RouteBuilder("test.unknown_cat", source="timer:60s")
    assert is_runtime_protocol_conformant(rb, "NotACategory") is False
