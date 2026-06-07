# ruff: noqa: S101
"""Unit tests for DataQualityMonitor (services/ops/data_quality.py)."""

from __future__ import annotations

import pytest

from src.backend.services.ops.data_quality import (
    DataQualityMonitor,
    DQCheckResult,
    DQRule,
    DQSeverity,
    get_dq_monitor,
)


@pytest.fixture()
def monitor() -> DataQualityMonitor:
    return DataQualityMonitor()


# ── DQCheckResult ───────────────────────────────────────────────


def test_dq_check_result_is_clean_when_empty() -> None:
    result = DQCheckResult()
    assert result.is_clean is True
    assert result.passed == 0
    assert result.failed == 0


def test_dq_check_result_not_clean_with_violations() -> None:
    from src.backend.services.ops.data_quality import DQViolation

    result = DQCheckResult(
        violations=[DQViolation("r1", "f1", DQSeverity.WARNING, "msg")],
        passed=1,
        failed=1,
    )
    assert result.is_clean is False


# ── add_rule / list_rules ───────────────────────────────────────


def test_add_rule_and_list_rules(monitor: DataQualityMonitor) -> None:
    rule = DQRule(name="not_null_name", field="name", check="not_null")
    monitor.add_rule(rule)
    rules = monitor.list_rules()
    assert len(rules) == 1
    assert rules[0]["name"] == "not_null_name"
    assert rules[0]["check"] == "not_null"
    assert rules[0]["enabled"] is True


def test_add_rules_bulk(monitor: DataQualityMonitor) -> None:
    rules = [
        DQRule(name="r1", field="a", check="not_null"),
        DQRule(name="r2", field="b", check="type", params={"type": "int"}),
    ]
    monitor.add_rules(rules)
    assert len(monitor.list_rules()) == 2


# ── not_null ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_not_null_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    result = await monitor.check({"name": "Alice"})
    assert result["is_clean"] is True
    assert result["passed"] == 1
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_check_not_null_fails_on_none(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    result = await monitor.check({"name": None})
    assert result["is_clean"] is False
    assert result["failed"] == 1
    assert result["violations"][0]["message"] == "Field 'name' is null/empty"


@pytest.mark.asyncio
async def test_check_not_null_fails_on_empty_string(
    monitor: DataQualityMonitor,
) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    result = await monitor.check({"name": ""})
    assert result["is_clean"] is False


# ── type ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_type_int_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="t1", field="age", check="type", params={"type": "int"})
    )
    result = await monitor.check({"age": 30})
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_check_type_int_fails_on_string(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="t1", field="age", check="type", params={"type": "int"})
    )
    result = await monitor.check({"age": "thirty"})
    assert result["is_clean"] is False
    assert "Expected int, got str" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_check_type_float_accepts_int(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="t1", field="score", check="type", params={"type": "float"})
    )
    result = await monitor.check({"score": 5})
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_check_type_none_is_ignored(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="t1", field="age", check="type", params={"type": "int"})
    )
    result = await monitor.check({"age": None})
    assert result["is_clean"] is True


# ── range ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_range_within_bounds(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="r1", field="age", check="range", params={"min": 0, "max": 120})
    )
    result = await monitor.check({"age": 25})
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_check_range_below_min(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="r1", field="age", check="range", params={"min": 0}))
    result = await monitor.check({"age": -5})
    assert result["is_clean"] is False
    assert "< min" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_check_range_above_max(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="r1", field="age", check="range", params={"max": 100}))
    result = await monitor.check({"age": 150})
    assert result["is_clean"] is False
    assert "> max" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_check_range_non_numeric_ignored(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="r1", field="age", check="range", params={"min": 0}))
    result = await monitor.check({"age": "old"})
    assert result["is_clean"] is True


# ── unique ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_unique_finds_duplicate(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="u1", field="id", check="unique"))
    result = await monitor.check([{"id": "A"}, {"id": "A"}])
    assert result["is_clean"] is False
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_check_unique_passes_when_different(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="u1", field="id", check="unique"))
    result = await monitor.check([{"id": "A"}, {"id": "B"}])
    assert result["is_clean"] is True


# ── outlier ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_outlier_ignored_until_10_samples(
    monitor: DataQualityMonitor,
) -> None:
    monitor.add_rule(DQRule(name="o1", field="val", check="outlier"))
    for i in range(9):
        result = await monitor.check({"val": float(i)})
        assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_check_outlier_detects_anomaly(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="o1", field="val", check="outlier"))
    # seed 10 samples ~ 0..9
    for i in range(10):
        await monitor.check({"val": float(i)})
    # mean=4.5, stddev ~3.03, z for 100 ~31.5 >> 3
    result = await monitor.check({"val": 100.0})
    assert result["is_clean"] is False
    assert "Outlier" in result["violations"][0]["message"]
    assert result["violations"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_check_outlier_high_z_still_warning(monitor: DataQualityMonitor) -> None:
    """data_quality outlier always uses WARNING severity (no critical level)."""
    monitor.add_rule(
        DQRule(name="o1", field="val", check="outlier", params={"z_threshold": 3.0})
    )
    for i in range(10):
        await monitor.check({"val": float(i)})
    result = await monitor.check({"val": 1000.0})
    assert result["is_clean"] is False
    assert result["violations"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_check_outlier_non_numeric_ignored(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="o1", field="val", check="outlier"))
    result = await monitor.check({"val": "big"})
    assert result["is_clean"] is True


# ── disabled rule ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_rule_skipped(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null", enabled=False))
    result = await monitor.check({"name": None})
    assert result["is_clean"] is True
    assert result["passed"] == 0
    assert result["failed"] == 0


# ── list input ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_accepts_list(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    result = await monitor.check([{"name": "A"}, {"name": None}])
    assert result["passed"] == 1
    assert result["failed"] == 1


# ── stats ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_tracks_checks(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    await monitor.check({"name": "A"})
    await monitor.check({"name": None})
    stats = await monitor.stats(dataset="default")
    assert stats["dataset"] == "default"
    assert stats["checks"] == 2
    assert stats["violations"] == 1


@pytest.mark.asyncio
async def test_stats_all_datasets(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(DQRule(name="nn", field="name", check="not_null"))
    await monitor.check({"name": "A"}, dataset="ds1")
    await monitor.check({"name": "B"}, dataset="ds2")
    stats = await monitor.stats()
    assert "ds1" in stats
    assert "ds2" in stats


# ── schema_infer ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_infer_basic(monitor: DataQualityMonitor) -> None:
    result = await monitor.schema_infer({"name": "Alice", "age": 30})
    assert result["fields"] == 2
    assert result["schema"]["name"] == "str"
    assert result["schema"]["age"] == "int"
    assert result["drift"] == {}


@pytest.mark.asyncio
async def test_schema_infer_drift_detected(monitor: DataQualityMonitor) -> None:
    await monitor.schema_infer({"name": "Alice"}, dataset="ds")
    result = await monitor.schema_infer({"name": "Alice", "age": 30}, dataset="ds")
    assert result["drift"] == {"age": "new_field"}


@pytest.mark.asyncio
async def test_schema_infer_missing_field(monitor: DataQualityMonitor) -> None:
    await monitor.schema_infer({"name": "Alice", "age": 30}, dataset="ds")
    result = await monitor.schema_infer({"name": "Alice"}, dataset="ds")
    assert result["drift"] == {"age": "missing_field"}


@pytest.mark.asyncio
async def test_schema_infer_multiple_types(monitor: DataQualityMonitor) -> None:
    result = await monitor.schema_infer([{"v": 1}, {"v": "a"}])
    assert "str" in result["schema"]["v"]
    assert "int" in result["schema"]["v"]


# ── singleton ───────────────────────────────────────────────────


def test_get_dq_monitor_singleton() -> None:
    m1 = get_dq_monitor()
    m2 = get_dq_monitor()
    assert m1 is m2
