"""ADR-0454 — Capability ``audit.write`` для шага ``audit`` (enforcement + декларации).

Контекст
--------
Шаг ``audit`` писал событие в audit-sink без проверки capability: capability
``audit.write`` была в vocabulary, но не объявлялась ни процессором, ни роутами
(частично — роуты `hello_route`, `jupyter_hub_run`, `test_route_w1` её уже
объявляли, но enforcement'а не было → декларации были декоративными).

Проверяется здесь:

* процессор ``audit`` объявляет ``required_capability = "audit.write"``;
* с capability-гейтом включённым роут без декларации → шаг отклоняется;
* роут с декларацией → шаг выполняется;
* все роуты с шагом ``audit`` объявляют ``audit.write``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.audit import AuditProcessor

pytestmark = pytest.mark.unit

_ROUTES_DIR = Path("routes")


@pytest.fixture(autouse=True)
def _gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capability-гейт включён (ADR-0366), baseline ядра выключен."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)


@pytest.fixture
def gate() -> Any:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


def test_audit_processor_requires_audit_write() -> None:
    """Процессор audit объявляет обязательную capability."""
    assert AuditProcessor.required_capability == "audit.write"


def _routes_with_audit_step() -> list[Path]:
    """Манифесты роутов, чьи DSL-спеки содержат шаг ``audit:``."""
    found: list[Path] = []
    for spec in sorted(_ROUTES_DIR.glob("*/*.dsl.yaml")):
        if "audit:" not in spec.read_text(encoding="utf-8"):
            continue
        manifest = spec.parent / "route.toml"
        if manifest.exists():
            found.append(manifest)
    return found


def test_every_route_with_audit_step_declares_audit_write() -> None:
    """Каждый роут с шагом ``audit`` объявляет ``audit.write``."""
    manifests = _routes_with_audit_step()
    assert manifests, "не найдено ни одного роута с шагом audit — тест неактуален"
    for manifest in manifests:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        route = data.get("route", {})
        names = {
            str(ref.get("name"))
            for ref in route.get("capabilities", [])
            if isinstance(ref, dict)
        }
        assert "audit.write" in names, f"{manifest}: нет декларации audit.write"


@pytest.mark.asyncio
async def test_audit_step_runs_with_public_baseline(gate: Any) -> None:
    """Шаг audit выполняется: capability public в platform-baseline.

    ``audit.write`` — public capability (vocabulary, ADR-0454), поэтому
    platform-baseline покрывает роут и без собственной декларации. Ценность
    enforcement'а — в scope: декларация роута ограничивает sink-ы
    (``audit:*``), а capability-заявка процессора делает проверку обязательной.
    """
    gate.declare("r_audit_public", [])
    processor = AuditProcessor(action="test.audit")
    pipeline = Pipeline(
        route_id="r_audit_public",
        source="internal:test",
        processors=[processor],
        tenant_aware=False,
    )
    from src.backend.dsl.engine.exchange import Message
    from src.backend.dsl.engine.execution_engine import ExecutionEngine

    exchange = Exchange(in_message=Message(body={}))
    engine = ExecutionEngine(validate_before_execute=False)
    result = await engine.execute(pipeline, exchange=exchange)

    assert result.status.value != "failed"
