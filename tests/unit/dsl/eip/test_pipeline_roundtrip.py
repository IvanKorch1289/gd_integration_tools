"""Pipeline round-trip: ``to_yaml()`` ↔ ``load_pipeline_from_yaml()`` (Wave 18.U3).

Покрытие:
    * Pipeline c 15+ процессорами, имеющими ``to_spec()`` (redirect /
      windowed_dedup / windowed_collect / multicast_routes).
    * Round-trip: Pipeline → YAML → Pipeline.
    * Сравнение через ``[s.to_spec() for s in p.processors]``.
    * Препроверка: процессоры без ``to_spec()`` (LogProcessor) пропускаются.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.dsl.builder import RouteBuilder
from src.dsl.engine.pipeline import Pipeline
from src.dsl.yaml_loader import load_pipeline_from_yaml


def _build_rich_pipeline() -> Pipeline:
    """Строит Pipeline с 15+ to_spec-совместимыми процессорами."""
    return (
        RouteBuilder.from_("test.roundtrip", source="internal:test")
        # 5 redirect-процессоров на каждый mode/url_source
        .redirect(target_url="http://example.com/r1", status_code=302)
        .redirect(target_url="http://example.com/r2", status_code=308)
        .redirect(url_source="header", source_key="X-Redir")
        .redirect(url_source="body_field", source_key="meta.url", status_code=307)
        .redirect(url_source="exchange_var", source_key="redirect_to")
        .redirect(
            url_source="query_param",
            source_key="next",
            allowed_hosts=["a.com", "b.org"],
        )
        # 3 windowed_dedup для каждого режима
        .windowed_dedup("body.entity_id")
        .windowed_dedup("body.id", mode="last", window_seconds=120, key_prefix="ord")
        .windowed_dedup("body.k", mode="unique", key_prefix="hash")
        # 2 windowed_collect
        .windowed_collect("body.table", "body.entity_id")
        .windowed_collect(
            "body.t",
            "body.id",
            window_seconds=30,
            dedup_mode="first",
            inject_as="batch",
        )
        # 3 multicast_routes
        .multicast_routes(["r1", "r2"])
        .multicast_routes(
            ["a"], strategy="first_success", on_error="fail", timeout=10.0
        )
        .multicast_routes(["x", "y", "z"], on_error="continue", timeout=5.0)
        # Финальный redirect для ровно 16 процессоров
        .redirect(target_url="http://final.example/", status_code=301)
        .build(validate_actions=False)
    )


def test_pipeline_has_at_least_15_processors() -> None:
    """Sanity check: тестовая фикстура содержит не менее 15 процессоров."""
    p = _build_rich_pipeline()
    assert len(p.processors) >= 15


def test_pipeline_round_trip_yaml_specs_equal() -> None:
    """Все процессоры должны идентично восстанавливаться из YAML."""
    p = _build_rich_pipeline()
    yaml_str = p.to_yaml()
    p_loaded = load_pipeline_from_yaml(yaml_str)

    original_specs = [proc.to_spec() for proc in p.processors]
    loaded_specs = [proc.to_spec() for proc in p_loaded.processors]
    assert original_specs == loaded_specs


def test_pipeline_route_id_preserved() -> None:
    """route_id и source сохраняются через YAML round-trip."""
    p = _build_rich_pipeline()
    p_loaded = load_pipeline_from_yaml(p.to_yaml())
    assert p_loaded.route_id == p.route_id
    assert p_loaded.source == p.source


def test_processors_without_to_spec_are_dropped_silently() -> None:
    """Процессоры без ``to_spec()`` (например, LogProcessor) — не попадают в YAML.

    Это документированное поведение ``Pipeline.to_dict()``: пропускает None.
    """
    p = (
        RouteBuilder.from_("partial", source="internal:p")
        .log("info")  # LogProcessor.to_spec() = None
        .redirect(target_url="http://example.com/", status_code=302)
        .log("debug")
        .build(validate_actions=False)
    )
    yaml_str = p.to_yaml()
    p_loaded = load_pipeline_from_yaml(yaml_str)
    # На выход выйдет ровно один процессор (redirect).
    assert len(p_loaded.processors) == 1


def test_yaml_load_unknown_processor_raises() -> None:
    """Whitelist: неизвестное имя процессора → ValueError."""
    yaml_text = (
        "route_id: bad\n"
        "source: internal:b\n"
        "processors:\n"
        "  - __class__: {}\n"
    )
    with pytest.raises(ValueError, match="Unknown or forbidden processor"):
        load_pipeline_from_yaml(yaml_text)


def test_yaml_load_dunder_blocked() -> None:
    """Whitelist: dunder-имена запрещены (anti-RCE)."""
    yaml_text = (
        "route_id: bad\n"
        "source: internal:b\n"
        "processors:\n"
        "  - __init__: {}\n"
    )
    with pytest.raises(ValueError, match="Unknown or forbidden processor"):
        load_pipeline_from_yaml(yaml_text)


def test_yaml_load_private_blocked() -> None:
    """Whitelist: приватные имена (с префиксом ``_``) запрещены."""
    yaml_text = (
        "route_id: bad\n"
        "source: internal:b\n"
        "processors:\n"
        "  - _add: {}\n"
    )
    with pytest.raises(ValueError, match="Unknown or forbidden processor"):
        load_pipeline_from_yaml(yaml_text)


def test_yaml_load_missing_route_id_raises() -> None:
    """Отсутствие route_id в YAML → ValueError."""
    with pytest.raises(ValueError, match="route_id"):
        load_pipeline_from_yaml("source: internal:nope\n")
