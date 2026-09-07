"""Тесты DataQualityMonitor (T3 ratchet: data_quality пакет 9–23%→≥90%).

In-memory логика: check-правила по фактическим контрактам _apply_rule
(not_null/type/range/unique/regex_match/enum/length), schema_infer + drift,
stats, remediation (dq_remediation), registry singleton.
"""

from __future__ import annotations

import pytest

from src.backend.services.ops.data_quality import (
    DataQualityMonitor,
    DQRule,
    get_dq_monitor,
)


def _rule(check: str, field: str = "value", **params: object) -> DQRule:
    return DQRule(name=f"{check}_{field}", field=field, check=check, params=dict(params))


# ── check-правила (контракты ApplyMixin) ────────────────────────────


@pytest.mark.asyncio
async def test_check_not_null_and_pass() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("not_null"))
    clean = await m.check({"value": 42})
    assert clean["is_clean"] is True
    assert clean["passed"] == 1
    bad = await m.check({"value": ""})
    assert bad["is_clean"] is False
    assert bad["failed"] == 1
    assert bad["violations"][0]["message"].startswith("Field 'value'")


@pytest.mark.asyncio
async def test_check_range_violation_and_bool_exclusion() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("range", min=0, max=100))
    assert (await m.check({"value": 50}))["failed"] == 0
    assert (await m.check({"value": 150}))["failed"] == 1
    # bool исключён из numeric-проверки (isinstance(True, int))
    assert (await m.check({"value": True}))["failed"] == 0


@pytest.mark.asyncio
async def test_check_regex_match_and_missing_pattern() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("regex_match", pattern=r"^\d+$"))
    assert (await m.check({"value": "12345"}))["failed"] == 0
    assert (await m.check({"value": "abc"}))["failed"] == 1
    # regex_match без pattern -> violation (missing param, ERROR)
    m2 = DataQualityMonitor()
    m2.add_rule(_rule("regex_match", field="value"))
    result = await m2.check({"value": "x"})
    assert result["failed"] == 1
    assert "missing 'pattern'" in result["violations"][0]["message"]


@pytest.mark.asyncio
async def test_check_enum_uses_values_param() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("enum", values=["a", "b"]))
    assert (await m.check({"value": "a"}))["failed"] == 0
    assert (await m.check({"value": "c"}))["failed"] == 1
    assert (await m.check({"value": None}))["failed"] == 0  # None пропускается


@pytest.mark.asyncio
async def test_check_type_uses_type_param() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("type", type="float"))
    assert (await m.check({"value": 3}))["failed"] == 0  # int допустим для float
    assert (await m.check({"value": "x"}))["failed"] == 1


@pytest.mark.asyncio
async def test_check_unique_duplicates_across_dataset() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("unique"))
    data = [{"value": 1}, {"value": 1}, {"value": 2}]
    result = await m.check(data)
    assert result["failed"] == 1  # второй «1» — дубликат
    assert result["violations"][0]["message"].startswith("Duplicate value")


@pytest.mark.asyncio
async def test_check_length_boundaries() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("length", min=2, max=5))
    assert (await m.check({"value": "abc"}))["failed"] == 0
    assert (await m.check({"value": "a"}))["failed"] == 1
    assert (await m.check({"value": "abcdef"}))["failed"] == 1


@pytest.mark.asyncio
async def test_check_disabled_rule_skipped() -> None:
    m = DataQualityMonitor()
    rule = _rule("not_null")
    rule.enabled = False
    m.add_rule(rule)
    result = await m.check({"value": None})
    # правило пропущено целиком: ни passed, ни failed
    assert result["passed"] == 0 and result["failed"] == 0


@pytest.mark.asyncio
async def test_check_unknown_check_returns_none() -> None:
    """Неизвестный check -> case _: None -> passed (без violation)."""
    m = DataQualityMonitor()
    m.add_rule(_rule("nonexistent_check"))
    assert (await m.check({"value": 1}))["passed"] == 1


@pytest.mark.asyncio
async def test_check_list_data_and_stats_accumulation() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("not_null"))
    data = [{"value": 1}, {"value": None}, {"value": 2}]
    await m.check(data, dataset="ds1")
    result = await m.check(data, dataset="ds1")
    stats = await m.stats("ds1")
    assert stats["checks"] == 6
    assert stats["violations"] == 2
    assert result["passed"] + result["failed"] == 3


# ── schema_infer + drift ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_infer_and_drift_detection() -> None:
    m = DataQualityMonitor()
    first = await m.schema_infer({"a": 1, "b": "x"}, dataset="ds")
    assert first["schema"] == {"a": "int", "b": "str"}
    assert first["drift"] == {}

    second = await m.schema_infer({"a": 1, "c": True}, dataset="ds")
    assert second["drift"]["c"] == "new_field"
    assert second["drift"]["b"] == "missing_field"


@pytest.mark.asyncio
async def test_stats_overall_view() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("not_null"))
    await m.check({"value": None}, dataset="ds")
    stats = await m.stats()
    assert stats.get("ds", {}).get("violations") == 1


# ── remediation (синхронный) ────────────────────────────────────────


def test_remediate_null_default_and_range_clip() -> None:
    m = DataQualityMonitor()
    m.add_rules(
        [
            _rule("not_null", field="name"),
            _rule("range", field="amount", min=0, max=100),
        ],
    )
    data = {"name": None, "amount": 250}
    result = m.remediate(data)
    assert result.data["name"] is not None
    assert result.data["amount"] == 100
    assert result.fixes_applied >= 2


def test_remediate_clean_data_no_fixes() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("not_null", field="name"))
    result = m.remediate({"name": "ok"})
    assert result.fixes_applied == 0


# ── registry singleton ──────────────────────────────────────────────


def test_get_dq_monitor_singleton() -> None:
    assert get_dq_monitor() is get_dq_monitor()
    assert isinstance(get_dq_monitor(), DataQualityMonitor)


# ── дополнительные apply-хелперы (date_format / cross_field / outlier) ──


@pytest.mark.asyncio
async def test_check_date_format_valid_and_invalid() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("date_format", format="%Y-%m-%d"))
    assert (await m.check({"value": "2026-09-06"}))["failed"] == 0
    assert (await m.check({"value": "06-09-2026"}))["failed"] == 1
    assert (await m.check({"value": None}))["failed"] == 0  # None пропускается


@pytest.mark.asyncio
async def test_check_cross_field_comparison() -> None:
    m = DataQualityMonitor()
    m.add_rule(_rule("cross_field", field="end", other_field="start", operator="ge"))
    ok = await m.check({"start": 1, "end": 5})
    bad = await m.check({"start": 5, "end": 1})
    # unknown operator не влияет на ok-кейс; bad-кейс ловится отдельно
    assert ok["failed"] == 0
    assert bad["failed"] == 1


@pytest.mark.asyncio
async def test_check_outlier_zscore_needs_history() -> None:
    """outlier требует >=10 значений истории; до неё — без violation."""
    m = DataQualityMonitor()
    m.add_rule(_rule("outlier"))
    for i in range(12):
        await m.check({"value": 10 + i}, dataset="ds")
    result = await m.check({"value": 1000}, dataset="ds")
    assert result["failed"] == 1
    assert "outlier" in result["violations"][0]["message"].lower() or (
        "z-score" in result["violations"][0]["message"].lower()
    )


@pytest.mark.asyncio
async def test_check_json_schema_violation() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    m = DataQualityMonitor()
    m.add_rule(_rule("json_schema", schema={"type": "object"}))
    result = await m.check({"value": {"a": 1}})
    assert result["failed"] == 0
    result_bad = await m.check({"value": "not-an-object"}, dataset="ds2")
    assert result_bad["failed"] == 1
    del jsonschema
