"""ADR-0454 — Capability ``audit.write`` для шага ``audit`` (enforcement + декларации).

Контекст
--------
Шаг ``audit`` писал событие в audit-sink без проверки capability: capability
``audit.write`` была в vocabulary, но не объявлялась ни процессором, ни роутами
(частично — роуты `hello_route`, `jupyter_hub_run`, `test_route_w1` её уже
объявляли, но enforcement'а не было → декларации были декоративными).

Проверяется здесь:

* процессор ``audit`` объявляет ``required_capability = "audit.write"`` и
  **сам** вызывает ``auth_check`` (enforcement на уровне процессора — как у
  БД- и RPA-процессоров, ADR-0393/ADR-0401);
* роут без декларации → шаг отклоняется (sink не вызывается);
* роут с декларацией ``audit.write`` (scope ``audit:*``) → шаг выполняется;
* scope проверяется: декларация другого scope не покрывает запрос;
* все роуты с шагом ``audit`` объявляют ``audit.write``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.audit import AuditProcessor

pytestmark = pytest.mark.unit

#: Реальный capability-гейт: без этой подмены autouse-фикстура
#: ``tests/unit/dsl/conftest.py`` подменяет ``BaseProcessor.auth_check`` на
#: «всегда разрешено» (ADR-0393) — и проверка гейта была бы вакуумной.
REAL_CAPABILITY_GATE = True

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


async def _run_audit_step(route_id: str) -> tuple[Any, MagicMock]:
    """Прогоняет pipeline из одного шага ``audit`` с замоканным sink'ом.

    Args:
        route_id: Имя роута (namespace capability-гейта).

    Returns:
        Кортеж ``(exchange, store)`` — результат выполнения и sink-мок.

    """
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="hash-abc")
    processor = AuditProcessor(action="test.audit")
    pipeline = Pipeline(
        route_id=route_id,
        source="internal:test",
        processors=[processor],
        tenant_aware=False,
    )
    exchange = Exchange(in_message=Message(body={}))
    engine = ExecutionEngine(validate_before_execute=False)
    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        result = await engine.execute(pipeline, exchange=exchange)
    return result, fake_store


@pytest.mark.asyncio
async def test_audit_step_denied_without_declaration(gate: Any) -> None:
    """Роут без декларации ``audit.write`` → шаг отклонён, sink не вызван."""
    result, store = await _run_audit_step("r_audit_no_decl")

    assert result.status.value == "failed", (
        "шаг audit без декларации capability должен быть отклонён, "
        f"получено status={result.status.value!r}"
    )
    assert "audit.write" in (result.error or ""), (
        f"в ошибке должно быть имя capability, получено: {result.error!r}"
    )
    assert store.append.await_count == 0, "sink не должен вызываться при отказе"


@pytest.mark.asyncio
async def test_audit_step_allowed_with_declaration(gate: Any) -> None:
    """Роут с декларацией ``audit.write`` (scope ``audit:*``) → шаг выполнен."""
    gate.declare("r_audit_ok", [CapabilityRef(name="audit.write", scope="audit:*")])

    result, store = await _run_audit_step("r_audit_ok")

    assert result.status.value != "failed", (
        f"шаг audit с объявленной capability должен выполняться, "
        f"получено status={result.status.value!r} error={result.error!r}"
    )
    assert store.append.await_count == 1
    assert result.properties["audit_event_hash"] == "hash-abc"


@pytest.mark.asyncio
async def test_audit_step_denied_on_scope_mismatch(gate: Any) -> None:
    """Декларация с другим scope не покрывает запрос шага."""
    gate.declare(
        "r_audit_scope", [CapabilityRef(name="audit.write", scope="audit:other")]
    )

    result, store = await _run_audit_step("r_audit_scope")

    assert result.status.value == "failed"
    assert store.append.await_count == 0
