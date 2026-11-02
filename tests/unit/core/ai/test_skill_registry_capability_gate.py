"""Capability-проверка skill'ов через capability-гейт (ADR-0416, дефект 1).

До ADR-0416 :meth:`SkillRegistry.invoke` искал символ
``_global_capability_check`` в ``core/plugin_runtime/sandbox.py`` — такого
символа **не существует**. Блок проверки был мёртвым, поэтому
``SkillSpec.capabilities`` из ``plugin.toml`` **не проверялись никогда**
(fail-open): skill с недекларированной capability выполнялся как ни в
чём не бывало.

Теперь проверка идёт напрямую через process-wide singleton
``get_capability_gate()``; namespace — плагин-владелец skill'а
(``plugin.toml::name``).

Проверяется:

* capability, не объявленная плагином → PermissionError (deny);
* объявленная capability → skill выполняется;
* недоступный capability-гейт → PermissionError (fail-closed);
* отказ фиксируется audit-событием ``capability.check``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.ai.skill_registry import SkillRegistry
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)
from src.backend.core.security.capabilities.models import CapabilityRef

pytestmark = pytest.mark.unit

PLUGIN_NAME = "test_skill_plugin"
MODULE_NAME = "tests.unit.core.ai.test_skill_registry_capability_gate"

PLUGIN_TOML = f"""
name = "{PLUGIN_NAME}"
version = "0.1.0"

[[skill]]
id = "demo.score"
version = "1.0.0"
handler = "{MODULE_NAME}:_skill_handler"
description = "demo skill"
capabilities = ["db.read.orders"]
"""


def _skill_handler(**kwargs: Any) -> dict[str, Any]:
    """Handler skill'а для тестов (вызывается только после проверки)."""
    return {"ok": True, "kwargs": kwargs}


@pytest.fixture
def gate() -> Iterator[CapabilityGate]:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    """Реестр с одним skill'ом из plugin.toml."""
    manifest = tmp_path / "plugin.toml"
    manifest.write_text(PLUGIN_TOML, encoding="utf-8")
    skill_registry = SkillRegistry()
    skill_registry.from_toml_manifest(manifest)
    return skill_registry


@pytest.mark.asyncio
async def test_skill_capability_without_declaration_is_denied(
    registry: SkillRegistry, gate: CapabilityGate
) -> None:
    """Capability, не объявленная плагином-владельцем → deny (ADR-0416)."""
    with pytest.raises(PermissionError) as exc_info:
        await registry.invoke("demo.score", whitelist=[MODULE_NAME])

    assert "capability denied" in str(exc_info.value)
    assert "db.read" in str(exc_info.value)


@pytest.mark.asyncio
async def test_skill_capability_declared_by_owner_is_allowed(
    registry: SkillRegistry, gate: CapabilityGate
) -> None:
    """Объявленная владельцем capability → skill выполняется."""
    gate.declare(PLUGIN_NAME, [CapabilityRef(name="db.read", scope="orders")])

    result = await registry.invoke("demo.score", whitelist=[MODULE_NAME], value=42)

    assert result == {"ok": True, "kwargs": {"value": 42}}


@pytest.mark.asyncio
async def test_skill_capability_scope_mismatch_is_denied(
    registry: SkillRegistry, gate: CapabilityGate
) -> None:
    """Scope не покрыт декларацией → deny (scope ≠ blanket)."""
    gate.declare(PLUGIN_NAME, [CapabilityRef(name="db.read", scope="files")])

    with pytest.raises(PermissionError):
        await registry.invoke("demo.score", whitelist=[MODULE_NAME])


@pytest.mark.asyncio
async def test_skill_capability_check_is_fail_closed_without_gate(
    registry: SkillRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Недоступный capability-гейт → deny (fail-closed), а не «пропустить»."""
    import src.backend.core.security.capabilities.gate as gate_module

    def _boom() -> CapabilityGate:
        raise RuntimeError("gate unavailable")

    monkeypatch.setattr(gate_module, "get_capability_gate", _boom)

    with pytest.raises(PermissionError) as exc_info:
        await registry.invoke("demo.score", whitelist=[MODULE_NAME])

    assert "fail-closed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_skill_capability_denial_emits_audit_event(
    registry: SkillRegistry, gate: CapabilityGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отказ capability-гейта фиксируется audit-событием."""
    import src.backend.core.audit.facade as audit_facade

    events: list[dict[str, Any]] = []

    def _record(**kwargs: Any) -> None:
        events.append(kwargs)

    monkeypatch.setattr(audit_facade, "emit_audit", _record)

    with pytest.raises(PermissionError):
        await registry.invoke("demo.score", whitelist=[MODULE_NAME])

    assert events, "audit-событие capability.check не эмичено"
    event = events[0]
    assert event["event"] == "capability.check"
    assert event["outcome"] == "denied"
    assert event["details"]["skill_id"] == "demo.score"


@pytest.mark.asyncio
async def test_skill_without_capabilities_skips_check(
    tmp_path: Path, gate: CapabilityGate
) -> None:
    """Skill без объявленных capability — проверка не выполняется."""
    manifest = tmp_path / "plugin.toml"
    manifest.write_text(
        f"""
name = "{PLUGIN_NAME}"
version = "0.1.0"

[[skill]]
id = "demo.plain"
version = "1.0.0"
handler = "{MODULE_NAME}:_skill_handler"
description = "demo skill"
""",
        encoding="utf-8",
    )
    skill_registry = SkillRegistry()
    skill_registry.from_toml_manifest(manifest)

    result = await skill_registry.invoke("demo.plain", whitelist=[MODULE_NAME])

    assert result == {"ok": True, "kwargs": {}}


@pytest.mark.asyncio
async def test_skill_with_unknown_owner_is_denied(
    tmp_path: Path, gate: CapabilityGate
) -> None:
    """Manifest без поля ``name`` → владелец неизвестен → deny (fail-closed)."""
    manifest = tmp_path / "plugin.toml"
    manifest.write_text(
        f"""
version = "0.1.0"

[[skill]]
id = "demo.orphan"
version = "1.0.0"
handler = "{MODULE_NAME}:_skill_handler"
description = "demo skill"
capabilities = ["db.read.orders"]
""",
        encoding="utf-8",
    )
    skill_registry = SkillRegistry()
    skill_registry.from_toml_manifest(manifest)

    with pytest.raises(PermissionError) as exc_info:
        await skill_registry.invoke("demo.orphan", whitelist=[MODULE_NAME])

    assert "владелец неизвестен" in str(exc_info.value)
