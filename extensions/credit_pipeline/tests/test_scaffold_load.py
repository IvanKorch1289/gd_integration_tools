# ruff: noqa: S101
"""Smoke-тест для scaffold-плагина ``extensions/credit_pipeline``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с ядром ``0.2.5``;
* объявленные capabilities (net.outbound для SKB/НБКИ, db.* для credit_*,
  mq.publish для credit.events.*);
* :class:`CreditPipelinePlugin` импортируется и lifecycle-хуки stub'а
  отрабатывают без ошибок.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from extensions.credit_pipeline.plugin import CreditPipelinePlugin
from src.backend.core.interfaces.plugin import BasePlugin
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
    assert manifest.version == "0.0.1"
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
    assert plugin.version == "0.0.1"


@pytest.mark.asyncio
async def test_credit_pipeline_scaffold_lifecycle_runs() -> None:
    """Все lifecycle-хуки scaffold'а отрабатывают без ошибок."""
    plugin = CreditPipelinePlugin()

    class _StubCtx:
        plugin_name = "credit_pipeline"
        actions = None
        repositories = None
        processors = None
        config: dict = {}

    await plugin.on_load(_StubCtx())  # type: ignore[arg-type]
    await plugin.on_register_actions(None)  # type: ignore[arg-type]
    await plugin.on_register_repositories(None)  # type: ignore[arg-type]
    await plugin.on_register_processors(None)  # type: ignore[arg-type]
    await plugin.on_shutdown()
