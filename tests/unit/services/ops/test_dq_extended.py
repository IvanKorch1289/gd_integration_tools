"""Unit tests for extended DQ rule types (S50 W1).

v21 §7.1: Data Quality Framework — extended dq_check 49→300 LOC.
New check types: regex_match, enum, length, date_format, cross_field, json_schema, cardinality.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.services.ops.data_quality import DataQualityMonitor, DQRule, DQSeverity


@pytest.fixture
def monitor() -> DataQualityMonitor:
    return DataQualityMonitor()


# ── regex_match ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regex_match_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="email_fmt",
            field="email",
            check="regex_match",
            params={"pattern": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"},
        )
    )
    result = await monitor.check({"email": "user@example.com"}, dataset="users")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_regex_match_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="email_fmt",
            field="email",
            check="regex_match",
            params={"pattern": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"},
        )
    )
    result = await monitor.check({"email": "not-an-email"}, dataset="users")
    assert result["is_clean"] is False
    assert result["violations"][0]["rule"] == "email_fmt"


@pytest.mark.asyncio
async def test_regex_match_missing_pattern(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="r", field="x", check="regex_match", params={})
    )
    result = await monitor.check({"x": "anything"}, dataset="d")
    assert result["is_clean"] is False
    assert "missing 'pattern'" in result["violations"][0]["message"]


# ── enum ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enum_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="status_enum",
            field="status",
            check="enum",
            params={"values": ["active", "inactive", "pending"]},
        )
    )
    result = await monitor.check({"status": "active"}, dataset="users")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_enum_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="status_enum",
            field="status",
            check="enum",
            params={"values": ["active", "inactive"]},
        )
    )
    result = await monitor.check({"status": "deleted"}, dataset="users")
    assert result["is_clean"] is False


# ── length ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_length_min_max_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="name_length",
            field="name",
            check="length",
            params={"min": 2, "max": 50},
        )
    )
    result = await monitor.check({"name": "John"}, dataset="users")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_length_min_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="name_length",
            field="name",
            check="length",
            params={"min": 5},
        )
    )
    result = await monitor.check({"name": "Bob"}, dataset="users")
    assert result["is_clean"] is False
    assert "< min 5" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_length_max_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="bio_length",
            field="bio",
            check="length",
            params={"max": 10},
        )
    )
    result = await monitor.check({"bio": "x" * 20}, dataset="users")
    assert result["is_clean"] is False


@pytest.mark.asyncio
async def test_length_null_skipped(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="name_length", field="name", check="length", params={"min": 1})
    )
    result = await monitor.check({"name": None}, dataset="users")
    assert result["is_clean"] is True  # null skipped


# ── date_format ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_date_format_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="dob_fmt",
            field="dob",
            check="date_format",
            params={"format": "%Y-%m-%d"},
        )
    )
    result = await monitor.check({"dob": "1990-05-15"}, dataset="users")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_date_format_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="dob_fmt",
            field="dob",
            check="date_format",
            params={"format": "%Y-%m-%d"},
        )
    )
    result = await monitor.check({"dob": "05/15/1990"}, dataset="users")
    assert result["is_clean"] is False


# ── cross_field ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_field_eq_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="confirm_match",
            field="password",
            check="cross_field",
            params={"other_field": "password_confirm", "operator": "eq"},
        )
    )
    result = await monitor.check(
        {"password": "x", "password_confirm": "x"}, dataset="users"
    )
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_cross_field_eq_fails(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="confirm_match",
            field="password",
            check="cross_field",
            params={"other_field": "password_confirm", "operator": "eq"},
        )
    )
    result = await monitor.check(
        {"password": "x", "password_confirm": "y"}, dataset="users"
    )
    assert result["is_clean"] is False


@pytest.mark.asyncio
async def test_cross_field_lt_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="date_range",
            field="start_date",
            check="cross_field",
            params={"other_field": "end_date", "operator": "lt"},
        )
    )
    result = await monitor.check(
        {"start_date": "2026-01-01", "end_date": "2026-12-31"},
        dataset="events",
    )
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_cross_field_missing_other_field(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="r",
            field="a",
            check="cross_field",
            params={},  # no other_field
        )
    )
    result = await monitor.check({"a": 1, "b": 2}, dataset="d")
    assert result["is_clean"] is False
    assert "missing 'other_field'" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_cross_field_unknown_operator(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="r",
            field="a",
            check="cross_field",
            params={"other_field": "b", "operator": "bogus"},
        )
    )
    result = await monitor.check({"a": 1, "b": 2}, dataset="d")
    assert "Unknown cross_field operator" in result["violations"][0]["message"]


# ── json_schema ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_json_schema_passes(monitor: DataQualityMonitor) -> None:
    pytest.importorskip("jsonschema")
    monitor.add_rule(
        DQRule(
            name="user_schema",
            field="profile",
            check="json_schema",
            params={
                "schema": {
                    "type": "object",
                    "properties": {"age": {"type": "integer", "minimum": 0}},
                    "required": ["age"],
                }
            },
        )
    )
    result = await monitor.check({"profile": {"age": 25}}, dataset="users")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_json_schema_fails(monitor: DataQualityMonitor) -> None:
    pytest.importorskip("jsonschema")
    monitor.add_rule(
        DQRule(
            name="user_schema",
            field="profile",
            check="json_schema",
            params={
                "schema": {
                    "type": "object",
                    "properties": {"age": {"type": "integer", "minimum": 0}},
                    "required": ["age"],
                }
            },
        )
    )
    result = await monitor.check({"profile": {"age": -1}}, dataset="users")
    assert result["is_clean"] is False


@pytest.mark.asyncio
async def test_json_schema_missing_schema_param(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(name="r", field="x", check="json_schema", params={})
    )
    result = await monitor.check({"x": {}}, dataset="d")
    assert result["is_clean"] is False
    assert "missing 'schema'" in result["violations"][0]["message"]


# ── cardinality ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cardinality_passes(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="unique_emails",
            field="email",
            check="cardinality",
            params={"max_count": 1},
        )
    )
    result = await monitor.check({"email": "a@b.com"}, dataset="d")
    assert result["is_clean"] is True


@pytest.mark.asyncio
async def test_cardinality_fails_on_duplicate(monitor: DataQualityMonitor) -> None:
    monitor.add_rule(
        DQRule(
            name="unique_emails",
            field="email",
            check="cardinality",
            params={"max_count": 1},
        )
    )
    await monitor.check({"email": "a@b.com"}, dataset="d")
    result = await monitor.check({"email": "a@b.com"}, dataset="d")
    assert result["is_clean"] is False
    assert "max_count 1" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_severity_override(monitor: DataQualityMonitor) -> None:
    """Custom severity per rule."""
    monitor.add_rule(
        DQRule(
            name="r",
            field="x",
            check="enum",
            params={"values": ["a"]},
            severity=DQSeverity.INFO,
        )
    )
    result = await monitor.check({"x": "b"}, dataset="d")
    assert result["violations"][0]["severity"] == "info"
