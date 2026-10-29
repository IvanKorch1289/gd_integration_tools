"""Каталог YAML-шагов DSL (ADR-0397, кластер D, дефект 6).

Каталог — единый источник истины для:
* допустимых имён шагов (публичные методы ``RouteBuilder``);
* capability, которую требует шаг (``required_capability`` процессора);
* JSON-Schema параметров шага (реестр ``@processor`` + сигнатура builder'а).

Тесты — «мягкий» CI-гейт: они фиксируют полноту покрытия и отсутствие
drift'а между захардкоженным списком LSP-completion и реальным API.
"""

from __future__ import annotations

from src.backend.dsl.builders.step_catalog import (
    builder_step_names,
    catalog_coverage,
    step_capability_map,
    step_schema_map,
)


def test_catalog_covers_all_public_builder_methods() -> None:
    """Каталог содержит все публичные методы RouteBuilder."""
    names = builder_step_names()
    assert len(names) > 400, "RouteBuilder потерял методы — проверьте рефакторинг"
    assert "http_call" in names
    assert "db_query_external" in names
    assert not any(name.startswith("_") for name in names)


def test_capability_map_is_built_from_processors() -> None:
    """Capability-карта приходит из required_capability процессоров."""
    mapping = step_capability_map()
    assert mapping["db_query_external"] == "db.read"
    assert mapping["rpa_click"] == "rpa.browser.click"
    assert mapping["agent_run"] == "ai.invoke"
    # Никаких «мёртвых» ключей, которых нет среди шагов.
    steps = set(builder_step_names())
    assert set(mapping) <= steps


def test_schema_map_covers_every_step() -> None:
    """Для каждого шага есть JSON-Schema (из реестра или по сигнатуре)."""
    schemas = step_schema_map()
    for name in builder_step_names():
        assert name in schemas, f"{name}: нет схемы"
        assert schemas[name].get("type") == "object"


def test_registry_schema_wins_over_signature_skeleton() -> None:
    """Для зарегистрированных процессоров берётся схема реестра (ADR-0058)."""
    schemas = step_schema_map()
    registry_schema = schemas["rpa_click"]
    assert "$schema" in registry_schema
    assert "$id" in registry_schema


def test_lsp_completions_have_no_drift() -> None:
    """Захардкоженный список LSP-completion не содержит несуществующих шагов."""
    from tools.dsl_lsp.schema_completion import STEP_COMPLETIONS

    steps = set(builder_step_names())
    unknown = [label for label, _detail, _snippet in STEP_COMPLETIONS if label not in steps]
    assert unknown == [], f"LSP-completion предлагает несуществующие шаги: {unknown}"


def test_catalog_coverage_is_reported() -> None:
    """Покрытие каталога измеримо (для мягкого CI-гейта)."""
    coverage = catalog_coverage()
    assert coverage["steps"] == len(builder_step_names())
    assert coverage["with_capability"] > 0
    assert coverage["with_capability"] <= coverage["steps"]
    assert coverage["with_registry_schema"] > 0
