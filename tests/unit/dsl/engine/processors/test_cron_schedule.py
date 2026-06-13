"""S103 W2 — tests для ``RouteBuilder.cron_schedule`` + ``CronScheduleProcessor``.

DSL skeleton: validates registration, validation, chainable.
"""
from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors.cron_schedule import (
    CronScheduleProcessor,
)


def test_cron_schedule_dsl_registers_processor() -> None:
    """``RouteBuilder.cron_schedule(...)`` — добавляет CronScheduleProcessor в pipeline."""
    b = RouteBuilder("test", source="timer:cron")
    result = b.cron_schedule(
        "nightly",
        cron_expr="*/5 * * * *",
        workflow_name="etl",
    )
    assert isinstance(result, RouteBuilder)
    assert result is b  # chainable, returns self
    assert len(b._processors) == 1
    p = b._processors[0]
    assert isinstance(p, CronScheduleProcessor)
    assert p.kind == "cron_schedule"
    assert p.workflow_name == "etl"
    assert p.cron_expr == "*/5 * * * *"


def test_cron_schedule_with_workflow_args() -> None:
    """``cron_schedule(..., workflow_args={...})`` — args сохраняются в processor."""
    b = RouteBuilder("test", source="timer:cron")
    b.cron_schedule(
        "nightly",
        cron_expr="0 0 * * *",
        workflow_name="etl",
        workflow_args={"source": "prod", "tenant": "t1"},
    )
    p = b._processors[0]
    assert p.workflow_args == {"source": "prod", "tenant": "t1"}


def test_cron_schedule_with_timezone() -> None:
    """``cron_schedule(..., timezone='Europe/Moscow')`` — timezone сохраняется."""
    b = RouteBuilder("test", source="timer:cron")
    b.cron_schedule(
        "msk_nightly",
        cron_expr="0 3 * * *",
        workflow_name="etl",
        timezone="Europe/Moscow",
    )
    p = b._processors[0]
    assert p.timezone == "Europe/Moscow"


def test_cron_schedule_chainable() -> None:
    """``cron_schedule()`` — chainable с другими DSL методами."""
    b = (
        RouteBuilder("test", source="timer:cron")
        .cron_schedule("n", cron_expr="*/5 * * * *", workflow_name="etl")
        .audit(action="scheduled")
    )
    assert len(b._processors) == 2
    assert isinstance(b._processors[0], CronScheduleProcessor)


def test_cron_schedule_processor_validates_cron() -> None:
    """``CronScheduleProcessor`` — валидирует 5-field cron_expr."""
    with pytest.raises(ValueError) as exc:
        CronScheduleProcessor(name="x", cron_expr="bad", workflow_name="y")
    assert "5-field" in str(exc.value)


def test_cron_schedule_processor_validates_name() -> None:
    """``CronScheduleProcessor`` — name обязателен."""
    with pytest.raises(ValueError) as exc:
        CronScheduleProcessor(name="", cron_expr="*/5 * * * *", workflow_name="y")
    assert "name" in str(exc.value).lower()


def test_cron_schedule_processor_validates_workflow() -> None:
    """``CronScheduleProcessor`` — workflow_name обязателен."""
    with pytest.raises(ValueError) as exc:
        CronScheduleProcessor(
            name="x", cron_expr="*/5 * * * *", workflow_name=""
        )
    assert "workflow_name" in str(exc.value).lower()


def test_cron_schedule_processor_to_dict() -> None:
    """``to_dict()`` — сериализует все поля для audit / spec dump."""
    p = CronScheduleProcessor(
        name="nightly",
        cron_expr="0 0 * * *",
        workflow_name="etl",
        workflow_args={"x": 1},
        timezone="UTC",
    )
    d = p.to_dict()
    assert d["kind"] == "cron_schedule"
    assert d["name"] == "nightly"
    assert d["cron_expr"] == "0 0 * * *"
    assert d["workflow_name"] == "etl"
    assert d["workflow_args"] == {"x": 1}
    assert d["timezone"] == "UTC"


def test_cron_schedule_processor_kind() -> None:
    """``kind`` — ``\"cron_schedule\"`` для runtime dispatch."""
    p = CronScheduleProcessor(
        name="x", cron_expr="*/5 * * * *", workflow_name="y"
    )
    assert p.kind == "cron_schedule"
