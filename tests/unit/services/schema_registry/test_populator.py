"""Тесты populator-функций ServiceSchemaRegistry (T3 ratchet 42%→≥90%).

Каждая populate_* тестируется с инжектируемым registry и фейковыми
источниками (processor specs, routes, actions, plugin manifests).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.schema_registry import populator
from src.backend.services.schema_registry.registry import (
    SchemaKind,
    ServiceSchemaRegistry,
)


def _fake_processor_spec(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        fqn=f"ns.{name}",
        name=name,
        namespace="core",
        spec_schema={"type": "object"},
        output_schema={"type": "object"},
        capabilities={"cap.a"},
        replaces=["old.name"],
        meta={"tier": 1},
    )


@pytest.mark.asyncio
async def test_populate_from_processor_registry() -> None:
    reg = ServiceSchemaRegistry()
    with patch(
        "src.backend.core.api.extensions.get_processor_registry"
    ) as mock_get:
        mock_get.return_value.list_specs = MagicMock(
            return_value=[
                _fake_processor_spec("alpha"),
                _fake_processor_spec("beta"),
            ]
        )
        count = populator.populate_from_processor_registry(reg)
    assert count == 2
    entries = reg.list_kind(SchemaKind.PROCESSOR)
    assert {e.name for e in entries} == {"ns.alpha", "ns.beta"}
    assert entries[0].meta["short_name"] in {"alpha", "beta"}
    assert entries[0].meta["replaces"] == ["old.name"]


@pytest.mark.asyncio
async def test_populate_from_routes_with_injected_registry() -> None:
    reg = ServiceSchemaRegistry()
    route_registry = SimpleNamespace(
        list_routes=lambda: ["r1", "r2"],
        get=lambda rid: SimpleNamespace(
            description=f"desc {rid}",
            source="yaml",
            feature_flag=None,
            processors=[object(), object()],
        ),
    )
    count = populator.populate_from_routes(route_registry, registry=reg)
    assert count == 2
    entries = reg.list_kind(SchemaKind.ROUTE)
    names = {e.name for e in entries}
    assert names == {"r1", "r2"}
    entry_r1 = next(e for e in entries if e.name == "r1")
    assert entry_r1.spec_schema["properties"]["route_id"]["const"] == "r1"
    assert entry_r1.meta["processors_count"] == 2


@pytest.mark.asyncio
async def test_populate_from_actions_with_specs() -> None:
    reg = ServiceSchemaRegistry()
    action_registry = SimpleNamespace(
        list_actions=lambda: ["b.act", "a.act"],
        get=lambda name: SimpleNamespace(
            tier=2,
            protocols=["rest", "grpc"],
            description=f"action {name}",
            payload_schema={"type": "object"},
            response_schema={"type": "string"},
        ),
    )
    with patch(
        "src.backend.core.api.extensions.action_handler_registry",
        action_registry,
    ):
        count = populator.populate_from_actions(reg)
    assert count == 2
    entries = reg.list_kind(SchemaKind.ACTION)
    assert [e.name for e in entries] == ["a.act", "b.act"]  # sorted
    assert entries[0].spec_schema == {"type": "object"}
    assert entries[0].meta["tier"] == 2
    assert entries[0].output_schema == {"type": "string"}


@pytest.mark.asyncio
async def test_populate_from_actions_registry_unavailable() -> None:
    reg = ServiceSchemaRegistry()
    with patch(
        "src.backend.core.api.extensions",
        SimpleNamespace(),  # нет action_handler_registry
    ):
        assert populator.populate_from_actions(reg) == 0


@pytest.mark.asyncio
async def test_populate_from_actions_registry_without_get() -> None:
    reg = ServiceSchemaRegistry()
    action_registry = SimpleNamespace(
        list_actions=lambda: ["x.act"]
    )  # get отсутствует -> getattr-ветка lambda _: None -> meta пустой
    with patch(
        "src.backend.core.api.extensions.action_handler_registry",
        action_registry,
    ):
        count = populator.populate_from_actions(reg)
    assert count == 1
    entries = reg.list_kind(SchemaKind.ACTION)
    assert entries[0].meta == {}
    assert entries[0].spec_schema is None


@pytest.mark.asyncio
async def test_populate_from_manifests_with_plugin_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = ServiceSchemaRegistry()
    plugin_registry = SimpleNamespace(
        list_plugins=lambda: [
            SimpleNamespace(
                name="credit_pipeline",
                version="1.0.0",
                capabilities=["credit.check"],
                requires_core=">=1.0",
            ),
            SimpleNamespace(name="anon"),  # без version/capabilities
        ]
    )
    import sys

    fake_module = SimpleNamespace(get_plugin_registry=lambda: plugin_registry)
    monkeypatch.setitem(sys.modules, "src.backend.core.plugin_runtime.registry", fake_module)
    count = populator.populate_from_manifests(reg)
    assert count == 2
    names = {e.name for e in reg.list_kind(SchemaKind.PLUGIN)}
    assert names == {"credit_pipeline", "anon"}


@pytest.mark.asyncio
async def test_populate_from_manifests_plugin_registry_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    reg = ServiceSchemaRegistry()

    class _BadModule:
        def get_plugin_registry(self) -> object:
            raise RuntimeError("not initialized")

    monkeypatch.setitem(sys.modules, "src.backend.core.plugin_runtime.registry", _BadModule())
    assert populator.populate_from_manifests(reg) == 0


@pytest.mark.asyncio
async def test_populate_from_manifests_without_list_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    reg = ServiceSchemaRegistry()
    fake_module = SimpleNamespace(get_plugin_registry=lambda: SimpleNamespace())
    monkeypatch.setitem(sys.modules, "src.backend.core.plugin_runtime.registry", fake_module)
    assert populator.populate_from_manifests(reg) == 0



# ── guard-ветки (fallback-пути) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_populate_from_actions_import_error_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_handler_registry недоступен (ImportError) -> 0 (119-120)."""
    import sys

    reg = ServiceSchemaRegistry()
    monkeypatch.setitem(sys.modules, "src.backend.core.api.extensions", None)
    assert populator.populate_from_actions(reg) == 0


@pytest.mark.asyncio
async def test_populate_from_actions_list_actions_missing_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry без list_actions -> AttributeError -> 0 (125-126)."""
    reg = ServiceSchemaRegistry()
    registry_without_list = SimpleNamespace()  # нет list_actions
    with patch(
        "src.backend.core.api.extensions.action_handler_registry",
        registry_without_list,
        create=True,
    ):
        assert populator.populate_from_actions(reg) == 0


@pytest.mark.asyncio
async def test_populate_from_manifests_import_error_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """plugin_runtime.registry отсутствует -> ImportError -> 0 (166-167)."""
    import sys

    reg = ServiceSchemaRegistry()
    monkeypatch.setitem(sys.modules, "src.backend.core.plugin_runtime.registry", None)
    assert populator.populate_from_manifests(reg) == 0


def test_populate_from_routes_default_registry_path() -> None:
    """Явный route_registry -> lazy-default не используется (78-80)."""
    reg = ServiceSchemaRegistry()
    route_registry = SimpleNamespace(
        list_routes=lambda: ["r9"],
        get=lambda rid: SimpleNamespace(
            description="d", source="dsl", feature_flag="flag", processors=[]
        ),
    )
    count = populator.populate_from_routes(route_registry, registry=reg)
    assert count == 1


# ── registry.py 344-346: _validate_entry (jsonschema) ───────────────


def test_register_validates_invalid_spec_schema_raises() -> None:
    """strict_validation=True + невалидная schema -> ValueError (344-346).

    Порог: _validate_entry вызывается только при strict_validation=True
    (default False — каталог аналитический, не authoritative).
    """
    from src.backend.services.schema_registry.registry import (
        SchemaEntry,
        SchemaKind,
        ServiceSchemaRegistry,
    )

    reg = ServiceSchemaRegistry(strict_validation=True)
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="broken.schema",
        spec_schema={"type": 123},
    )
    with pytest.raises(ValueError, match="Invalid JSON-Schema"):
        reg.register(entry)


def test_register_valid_schema_accepted() -> None:
    """Валидная схема регистрируется без ошибок (контрольный)."""
    from src.backend.services.schema_registry.registry import (
        SchemaEntry,
        SchemaKind,
        ServiceSchemaRegistry,
    )

    reg = ServiceSchemaRegistry()
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="good.schema",
        spec_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    reg.register(entry)
    assert reg.list_kind(SchemaKind.PROCESSOR)[0].name == "good.schema"
