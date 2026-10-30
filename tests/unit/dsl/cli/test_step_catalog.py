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
    registry_only_steps,
    step_capability_map,
    step_schema_map,
    yaml_step_for_registry_name,
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


class TestRegistrySync:
    """ADR-0399: каталог синхронизирован с реестром ``@processor``."""

    def test_renamed_steps_use_registry_schema(self) -> None:
        """``print_pdf``/``wait_for_selector`` берут схему реестра, а не каркас."""
        schemas = step_schema_map()
        for step, registry_name in (
            ("print_pdf", "rpa_pdf"),
            ("wait_for_selector", "rpa_wait_for"),
        ):
            schema = schemas[step]
            assert "$id" in schema, f"{step}: достался сигнатурный каркас"
            assert registry_name in schema["$id"], (
                f"{step}: ожидалась схема реестра {registry_name}"
            )

    def test_registry_only_steps_are_reported(self) -> None:
        """Процессоры реестра без YAML-шага перечислены отдельным списком."""
        only = registry_only_steps()
        assert only, "реестр не может быть пустым"
        assert "memory_recall" in only
        steps = set(builder_step_names())
        assert not (set(only) & steps)

    def test_yaml_step_for_registry_name(self) -> None:
        """Имя реестра → YAML-шаг (``rpa_pdf`` → ``print_pdf``)."""
        assert yaml_step_for_registry_name("rpa_pdf") == "print_pdf"
        assert yaml_step_for_registry_name("rpa_wait_for") == "wait_for_selector"
        assert yaml_step_for_registry_name("memory_recall") is None

    def test_coverage_reports_registry_only(self) -> None:
        """Покрытие каталога сообщает о процессорах без YAML-шага."""
        coverage = catalog_coverage()
        assert coverage["registry_only"] == len(registry_only_steps())
