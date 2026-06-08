# ruff: noqa: S101
"""Smoke-тесты для credit_pipeline v0.1.0 (S76 W1+W2).

Проверяют:
* parse manifest V11 (ADR-042);
* совместимость с ядром ``0.2.5``;
* объявленные capabilities (net.outbound для SKB/НБКИ, db.* для credit_*,
  mq.publish для credit.events.*);
* :class:`CreditPipelinePlugin` импортируется и lifecycle-хуки
  отрабатывают без ошибок;
* v0.1.0 — registered actions ``credit_pipeline.{score,parse,decide}``
  через mock registry (3 real handlers, не stubs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from extensions.credit_pipeline.plugin import CreditPipelinePlugin
from src.backend.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
)
from src.backend.services.plugins.manifest_v11 import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "extensions"
    / "credit_pipeline"
    / "plugin.toml"
)


def test_credit_pipeline_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром ``0.2.5``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "credit_pipeline"
    assert manifest.version == "0.1.0"
    assert manifest.is_compatible_with_core("0.2.5") is True
    assert manifest.tenant_aware is True


def test_credit_pipeline_capabilities_cover_skb_nbki_db_mq() -> None:
    """Manifest объявляет полный набор capability ресурсов кредитного конвейера."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    caps = {(c.name, c.scope) for c in manifest.capabilities}
    # Внешние API (через WAF).
    assert ("net.outbound", "*.skb-techno.ru") in caps
    assert ("net.outbound", "*.nbki.ru") in caps
    # БД ресурсы.
    assert ("db.read", "credit_applications") in caps
    assert ("db.write", "credit_applications") in caps
    assert ("db.read", "credit_reports") in caps
    assert ("db.write", "credit_reports") in caps
    # MQ события.
    assert ("mq.publish", "credit.events.*") in caps


def test_credit_pipeline_plugin_is_base_plugin_subclass() -> None:
    """``CreditPipelinePlugin`` — корректный :class:`BasePlugin`-наследник."""
    plugin = CreditPipelinePlugin()
    assert isinstance(plugin, BasePlugin)
    assert plugin.name == "credit_pipeline"
    assert plugin.version == "0.1.0"


def test_credit_pipeline_manifest_declares_three_actions() -> None:
    """v0.1.0: ``[provides].actions`` содержит 3 real actions."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    actions = set(manifest.provides.actions)
    assert actions == {
        "credit_pipeline.score",
        "credit_pipeline.parse",
        "credit_pipeline.decide",
    }


class _RecordingRegistry:
    """Минимальный mock ActionRegistryProtocol для smoke-теста."""

    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register(
        self, action_id: str, handler: Any, *, spec: Any | None = None
    ) -> None:
        self.registered[action_id] = handler


class _NoOpRegistry:
    """Mock RepositoryRegistryProtocol / ProcessorRegistryProtocol (defer S77+)."""

    def register_hook(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op для defer."""

    def override_method(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op для defer."""

    def register_class(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op для defer."""


@pytest.mark.asyncio
async def test_credit_pipeline_plugin_lifecycle_runs() -> None:
    """Все lifecycle-хуки v0.1.0 отрабатывают без ошибок."""
    plugin = CreditPipelinePlugin()
    noop = _NoOpRegistry()
    ctx = PluginContext(
        plugin_name="credit_pipeline",
        actions=noop,  # type: ignore[arg-type]
        repositories=noop,  # type: ignore[arg-type]
        processors=noop,  # type: ignore[arg-type]
        config={},
    )
    actions_registry: ActionRegistryProtocol = _RecordingRegistry()  # type: ignore[assignment]
    other_registry: Any = _NoOpRegistry()

    await plugin.on_load(ctx)
    await plugin.on_register_actions(actions_registry)
    await plugin.on_register_repositories(other_registry)  # type: ignore[arg-type]
    await plugin.on_register_processors(other_registry)  # type: ignore[arg-type]
    await plugin.on_shutdown()
    # v0.1.0: 3 actions зарегистрированы (не stubs).
    assert set(actions_registry.registered) == {  # type: ignore[attr-defined]
        "credit_pipeline.score",
        "credit_pipeline.parse",
        "credit_pipeline.decide",
    }
    for action_id, handler in actions_registry.registered.items():  # type: ignore[attr-defined]
        assert callable(handler), f"{action_id} handler is not callable"
