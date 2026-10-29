"""ADR-0393 — capability-гейт DSL: engine-уровневые тесты.

Ядро кластера G4 (волна 18):

* **Отказ capability-гейта обязан провалить маршрут.** Раньше
  ``BaseProcessor.auth_check`` делал ``set_error`` + ``stop()`` → статус
  оставался ``processing``, а ``ExecutionEngine._finalize`` вызывал
  ``exchange.complete()``, который обнулял ``error``. Клиент получал
  «успех», SLO — ``is_error=False``. Теперь отказ даёт ``failed``;
* **БД-шаги обязаны иметь capability.** Раньше ни один БД-процессор не
  объявлял ``required_capability`` → любой DSL-роут читал/писал любую БД;
* **Политика RPA в prod-профиле** — allow/deny согласно декларации роута.

Каталог намеренно вынесен из ``tests/unit/dsl/engine/processors/``: там
autouse-фикстура разрешает capability-гейт (для тестов поведения БД), а
здесь проверяется **настоящий** гейт.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit

#: Этот модуль проверяет РЕАЛЬНЫЙ capability-гейт.
REAL_CAPABILITY_GATE = True


@pytest.fixture
def gate() -> Iterator[CapabilityGate]:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


@pytest.fixture(autouse=True)
def gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime-enforcement capability-гейта включён (ADR-0366)."""
    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)


class _DeniedProcessor(BaseProcessor):
    """Процессор с capability, которую роут не объявил."""

    required_capability = "rpa.file.list"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Процессор не должен выполниться (доступ запрещён)."""
        if not await self.auth_check(exchange, action="read"):
            return
        exchange.set_property("executed", True)


class _Toucher(BaseProcessor):
    """Процессор без capability — выполняется всегда."""

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Пишет маркер выполнения."""
        exchange.set_property("touched", True)


def _pipeline(*processors: BaseProcessor, route_id: str = "r_cap_gate") -> Pipeline:
    """Собрать pipeline с заданными процессорами."""
    return Pipeline(
        route_id=route_id,
        source="internal:test",
        processors=list(processors),
        tenant_aware=False,
    )


# ── 1. Отказ capability-гейта → маршрут failed ────────────────────────────


async def test_denied_capability_marks_route_failed(gate: CapabilityGate) -> None:
    """Отказ capability-гейта проваливает маршрут (ADR-0393).

    Регрессия волны 18: ``DENIED → status: completed | error: None`` —
    клиент получал «успех», SLO-счётчик писал ``is_error=False``.
    """
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(_DeniedProcessor(), _Toucher())

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.failed
    assert result.error is not None
    assert "denied" in result.error
    # Шаги после отказа не выполняются.
    assert "touched" not in result.properties


async def test_denied_capability_does_not_complete_exchange(
    gate: CapabilityGate,
) -> None:
    """``exchange.complete()`` не вызывается после отказа (error не обнулён)."""
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(_DeniedProcessor())

    result = await engine.execute(pipeline, body={})

    assert result.error is not None
    assert result.out_message is None or result.out_message.body != {"ok": True}


async def test_declared_capability_allows_route(gate: CapabilityGate) -> None:
    """Объявленная роутом capability — маршрут выполняется."""
    gate.declare("r_cap_gate", [CapabilityRef(name="rpa.file.list", scope="**")])
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(_DeniedProcessor(), _Toucher())

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.completed
    assert result.error is None
    assert result.properties.get("touched") is True


# ── 2. БД-capability: deny без декларации, allow с декларацией ───────────


async def test_db_step_without_capability_declaration_is_denied(
    gate: CapabilityGate,
) -> None:
    """БД-шаг без декларации ``db.read`` → маршрут failed (ADR-0393)."""
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    processor = ExternalDbQueryProcessor(
        profile="sqlite_probe", sql="SELECT * FROM widgets"
    )
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.failed
    assert result.error is not None
    assert "db.read" in result.error


async def test_db_step_with_declared_capability_passes_gate(
    gate: CapabilityGate,
) -> None:
    """Объявленная ``db.read`` (scope = алиас ресурса) проходит гейт.

    Scope для внешней БД — имя профиля (тот же convention, что у
    ``ExternalDatabaseFacade`` и в ``plugin.toml``).
    """
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    gate.declare("r_cap_gate", [CapabilityRef(name="db.read", scope="sqlite_probe")])
    processor = ExternalDbQueryProcessor(
        profile="sqlite_probe", sql="SELECT * FROM widgets"
    )
    # Capability проходит — дальше шаг падает на отсутствии DI-провайдера
    # БД, но НЕ на capability-гейте.
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    assert result.error is None or "capability" not in result.error


async def test_db_write_capability_is_required_for_dml(gate: CapabilityGate) -> None:
    """DML требует ``db.write`` (а не ``db.read``)."""
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    gate.declare("r_cap_gate", [CapabilityRef(name="db.read", scope="sqlite_probe")])
    processor = ExternalDbQueryProcessor(
        profile="sqlite_probe", sql="DELETE FROM widgets WHERE id = 1"
    )
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.failed
    assert result.error is not None
    assert "db.write" in result.error


# ── 9. RPA в prod-профиле: allow/deny согласно политике ──────────────────


async def test_rpa_step_in_prod_profile_is_denied_without_declaration(
    gate: CapabilityGate,
) -> None:
    """Prod-политика: RPA-шаг без декларации capability → deny.

    В prod/staging ``dsl_capability_core_baseline_enabled`` выключен, а
    capability ``rpa.*`` не публична → RPA-шаги fail-closed, пока роут
    явно не объявит их (ADR-0393, «Политика capability-гейта»).
    """
    from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
        FileListProcessor,
    )

    processor = FileListProcessor(pattern="/data/*")
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.failed
    assert result.error is not None
    assert "rpa.file.list" in result.error


async def test_rpa_step_in_prod_profile_is_allowed_with_declaration(
    gate: CapabilityGate,
) -> None:
    """Prod-политика: RPA-шаг с объявленной capability → allow."""
    from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
        FileListProcessor,
    )

    gate.declare("r_cap_gate", [CapabilityRef(name="rpa.file.list", scope="**")])
    processor = FileListProcessor(pattern="/data/*")
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    # Capability не отказала — шаг упал уже по содержимому (каталога нет).
    assert result.error is None or "capability" not in result.error


async def test_rpa_step_denied_when_only_other_capability_declared(
    gate: CapabilityGate,
) -> None:
    """Декларация другой capability не открывает RPA-шаг."""
    from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
        FileListProcessor,
    )

    gate.declare("r_cap_gate", [CapabilityRef(name="net.outbound", scope="**")])
    processor = FileListProcessor(pattern="/data/*")
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = _pipeline(processor)

    result = await engine.execute(pipeline, body={})

    assert result.status == ExchangeStatus.failed
    assert result.error is not None
    assert "rpa.file.list" in result.error


# ── (2/9) Схема декларации capability в route.toml (ADR-0078/ADR-044) ────


def test_db_capability_declared_by_route_with_plugin_owner() -> None:
    """``db.read`` + scope алиаса ресурса покрывается плагином-владельцем.

    Схема декларации (ADR-0078): в ``route.toml`` — табличная форма
    ``[[route.capabilities]] name + scope``, scope = алиас ресурса
    (``orders``). Плагин-владелец объявляет ту же capability — тогда
    subset-инвариант (``route.capabilities ⊆ plugins ∪ public``) проходит
    и роут загружается.
    """
    from src.backend.core.security.capabilities import (
        CapabilityRef,
        check_capabilities_subset,
    )
    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )

    vocabulary = build_default_vocabulary()
    plugin_caps = {
        "core_entities_orders": (CapabilityRef(name="db.read", scope="orders"),)
    }

    check_capabilities_subset(
        route="r_cap_gate",
        route_caps=[CapabilityRef(name="db.read", scope="orders")],
        plugin_caps_by_name=plugin_caps,
        vocabulary=vocabulary,
    )


def test_rpa_capability_cannot_be_declared_without_plugin_owner() -> None:
    """RPA-capability без плагина-владельца роут объявить НЕ может.

    Capability ``rpa.*`` не публична → subset-инвариант отклоняет роут
    (``CapabilitySupersetError``) → роут не загрузился бы вовсе. Поэтому
    RPA-шаги в prod/staging остаются fail-closed, пока не появится
    плагин-владелец (ADR-0393, «Политика capability-гейта»).
    """
    from src.backend.core.security.capabilities import (
        CapabilityRef,
        CapabilitySupersetError,
        check_capabilities_subset,
    )
    from src.backend.core.security.capabilities.vocabulary import (
        build_default_vocabulary,
    )

    with pytest.raises(CapabilitySupersetError):
        check_capabilities_subset(
            route="r_cap_gate",
            route_caps=[CapabilityRef(name="rpa.file.list", scope="**")],
            plugin_caps_by_name={},
            vocabulary=build_default_vocabulary(),
        )
