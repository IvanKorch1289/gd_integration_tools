"""Unit tests для DataQualityMonitor.remediate() и dq_remediation strategies.

Sprint 54 W1: auto-remediation для data quality violations.
"""
from __future__ import annotations

import pytest

from src.backend.services.ops.data_quality import (
    DataQualityMonitor,
    DQRemediationResult,
    DQRule,
)
from src.backend.services.ops.dq_remediation import (
    CompositeRemediator,
    EnumFallbackRemediator,
    NullDefaultRemediator,
    RangeClipRemediator,
    RegexMaskRemediator,
    TypeCoerceRemediator,
    build_remediator,
)

# ── Remediator strategies ─────────────────────────────────────────────

class TestNullDefaultRemediator:
    def test_replaces_none(self) -> None:
        r = NullDefaultRemediator(default=0)
        assert r.remediate(None, {}) == 0

    def test_replaces_empty_string(self) -> None:
        r = NullDefaultRemediator(default="N/A")
        assert r.remediate("", {}) == "N/A"

    def test_replaces_empty_list(self) -> None:
        r = NullDefaultRemediator(default=[])
        assert r.remediate([], {}) == []

    def test_keeps_non_null(self) -> None:
        r = NullDefaultRemediator(default=0)
        assert r.remediate(42, {}) == 42
        assert r.remediate("hello", {}) == "hello"

    def test_params_override_default(self) -> None:
        r = NullDefaultRemediator(default=0)
        assert r.remediate(None, {"default": -1}) == -1


class TestRangeClipRemediator:
    def test_clips_below_min(self) -> None:
        r = RangeClipRemediator(min=0, max=100)
        assert r.remediate(-5, {}) == 0

    def test_clips_above_max(self) -> None:
        r = RangeClipRemediator(min=0, max=100)
        assert r.remediate(150, {}) == 100

    def test_keeps_in_range(self) -> None:
        r = RangeClipRemediator(min=0, max=100)
        assert r.remediate(42, {}) == 42

    def test_non_numeric_passthrough(self) -> None:
        r = RangeClipRemediator(min=0, max=100)
        assert r.remediate("abc", {}) == "abc"
        assert r.remediate(None, {}) is None
        assert r.remediate([1, 2], {}) == [1, 2]

    def test_bool_passthrough(self) -> None:
        r = RangeClipRemediator(min=0, max=1)
        # bool is technically int but should not be clipped
        assert r.remediate(True, {}) is True


class TestRegexMaskRemediator:
    def test_masks_non_matching(self) -> None:
        r = RegexMaskRemediator(mask="***")
        assert r.remediate("ABC", {"pattern": r"^\d+$"}) == "***"

    def test_keeps_matching(self) -> None:
        r = RegexMaskRemediator()
        assert r.remediate("12345", {"pattern": r"^\d+$"}) == "12345"

    def test_non_string_passthrough(self) -> None:
        r = RegexMaskRemediator()
        assert r.remediate(42, {"pattern": r".*"}) == 42

    def test_invalid_regex_passthrough(self) -> None:
        r = RegexMaskRemediator()
        assert r.remediate("abc", {"pattern": r"[unclosed"}) == "abc"

    def test_no_pattern_passthrough(self) -> None:
        r = RegexMaskRemediator()
        assert r.remediate("abc", {}) == "abc"


class TestEnumFallbackRemediator:
    def test_replaces_invalid(self) -> None:
        r = EnumFallbackRemediator(fallback="unknown")
        assert r.remediate("other", {"allowed": ["a", "b", "c"]}) == "unknown"

    def test_keeps_valid(self) -> None:
        r = EnumFallbackRemediator(fallback="unknown")
        assert r.remediate("a", {"allowed": ["a", "b"]}) == "a"

    def test_no_allowed_passthrough(self) -> None:
        r = EnumFallbackRemediator(fallback="x")
        assert r.remediate("anything", {}) == "anything"


class TestTypeCoerceRemediator:
    def test_coerce_to_int(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate("42", {"target_type": "int"}) == 42

    def test_coerce_to_float(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate("3.14", {"target_type": "float"}) == 3.14

    def test_coerce_to_str(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate(42, {"target_type": "str"}) == "42"

    def test_coerce_to_bool(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate(1, {"target_type": "bool"}) is True
        assert r.remediate(0, {"target_type": "bool"}) is False

    def test_same_type_passthrough(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate(42, {"target_type": "int"}) == 42

    def test_invalid_value_passthrough(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate("abc", {"target_type": "int"}) == "abc"

    def test_unknown_type_passthrough(self) -> None:
        r = TypeCoerceRemediator()
        assert r.remediate("x", {"target_type": "decimal"}) == "x"


class TestCompositeRemediator:
    def test_chain_runs_in_order(self) -> None:
        # null default + range clip
        rem = CompositeRemediator([
            NullDefaultRemediator(default=0),
            RangeClipRemediator(min=0, max=100),
        ])
        assert rem.remediate(None, {}) == 0  # null → 0
        assert rem.remediate(150, {}) == 100  # clip to 100
        assert rem.remediate(50, {}) == 50   # in range

    def test_stops_on_first_fix_by_default(self) -> None:
        # RangeClip would clip, but stop_on_fix prevents second remediator
        rem = CompositeRemediator([
            RangeClipRemediator(min=0, max=100),
            NullDefaultRemediator(default=999),  # should not be reached
        ])
        assert rem.remediate(150, {}) == 100  # clipped, not replaced with 999

    def test_empty_chain_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            CompositeRemediator([])

    def test_run_all_when_stop_on_fix_false(self) -> None:
        rem = CompositeRemediator([
            RangeClipRemediator(min=0, max=100),
            NullDefaultRemediator(default=999),
        ], stop_on_fix=False)
        # First clips 150 → 100, then null check (100 is not null) → 100
        assert rem.remediate(150, {}) == 100


# ── build_remediator factory ──────────────────────────────────────────

class TestBuildRemediator:
    def test_not_null(self) -> None:
        r = build_remediator("not_null", {"default": "n/a"})
        assert isinstance(r, NullDefaultRemediator)
        assert r.remediate(None, {}) == "n/a"

    def test_range(self) -> None:
        r = build_remediator("range", {"min": 0, "max": 10})
        assert isinstance(r, RangeClipRemediator)
        assert r.remediate(20, {}) == 10

    def test_regex(self) -> None:
        r = build_remediator("regex", {"pattern": r"^\d+$", "mask": "X"})
        assert isinstance(r, RegexMaskRemediator)
        assert r.remediate("abc", {"pattern": r"^\d+$", "mask": "X"}) == "X"

    def test_enum(self) -> None:
        r = build_remediator("enum", {"allowed": ["a"], "fallback": "?"})
        assert isinstance(r, EnumFallbackRemediator)
        assert r.remediate("b", {"allowed": ["a"], "fallback": "?"}) == "?"

    def test_type(self) -> None:
        r = build_remediator("type", {"target_type": "int"})
        assert isinstance(r, TypeCoerceRemediator)
        assert r.remediate("42", {"target_type": "int"}) == 42

    def test_unsupported_returns_none(self) -> None:
        assert build_remediator("unique", {}) is None
        assert build_remediator("outlier", {}) is None
        assert build_remediator("cardinality", {}) is None


# ── DataQualityMonitor.remediate() ────────────────────────────────────

class TestMonitorRemediate:
    def test_remediate_dict_with_null_default(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="amount_not_null", field="amount", check="not_null", params={"default": 0}))
        result = m.remediate({"amount": None, "name": "x"})
        assert result.data == {"amount": 0, "name": "x"}
        assert result.fixes_applied == 1
        assert len(result.violations) == 1
        assert result.violations[0].rule == "amount_not_null"

    def test_remediate_dict_with_range_clip(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="age_range", field="age", check="range", params={"min": 0, "max": 120}))
        result = m.remediate({"age": 150})
        assert result.data["age"] == 120
        assert result.fixes_applied == 1

    def test_remediate_list_of_dicts(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="x_null", field="x", check="not_null", params={"default": "fallback"}))
        result = m.remediate([{"x": None}, {"x": "value"}, {"x": ""}])
        assert result.data[0]["x"] == "fallback"
        assert result.data[1]["x"] == "value"  # unchanged
        assert result.data[2]["x"] == "fallback"  # empty → fallback
        assert result.fixes_applied == 2

    def test_remediate_no_fixes_needed(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="x_null", field="x", check="not_null", params={"default": "f"}))
        result = m.remediate({"x": "valid"})
        assert result.data == {"x": "valid"}
        assert result.fixes_applied == 0
        assert result.violations == []
        assert result.is_clean

    def test_remediate_disabled_rule_skipped(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(
            name="x_null", field="x", check="not_null",
            params={"default": "f"}, enabled=False,
        ))
        result = m.remediate({"x": None})
        assert result.data == {"x": None}  # not fixed
        assert result.fixes_applied == 0

    def test_remediate_unsupported_check_no_fix(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="x_unique", field="x", check="unique"))
        result = m.remediate({"x": "value"})
        assert result.data == {"x": "value"}
        assert result.fixes_applied == 0
        # unique check is not run here (it's a multi-record check)
        assert result.violations == []

    def test_remediate_returns_dq_remediation_result(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="x_null", field="x", check="not_null", params={"default": 0}))
        result = m.remediate({"x": None})
        assert isinstance(result, DQRemediationResult)
        assert isinstance(result.data, dict)
        assert isinstance(result.violations, list)
        assert isinstance(result.fixes_applied, int)

    def test_remediate_enum_fallback(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(
            name="status_enum", field="status", check="enum",
            params={"allowed": ["active", "inactive"], "fallback": "unknown"},
        ))
        result = m.remediate({"status": "deleted"})
        assert result.data["status"] == "unknown"
        assert result.fixes_applied == 1

    def test_remediate_regex_mask(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(
            name="phone_regex", field="phone", check="regex",
            params={"pattern": r"^\+\d{10,}$", "mask": "INVALID"},
        ))
        result = m.remediate({"phone": "abc"})
        assert result.data["phone"] == "INVALID"
        assert result.fixes_applied == 1

    def test_remediate_type_coerce(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(
            name="count_type", field="count", check="type",
            params={"target_type": "int"},
        ))
        result = m.remediate({"count": "42"})
        assert result.data["count"] == 42
        assert isinstance(result.data["count"], int)
        assert result.fixes_applied == 1

    def test_remediate_multiple_rules_compose(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="age_range", field="age", check="range", params={"min": 0, "max": 120}))
        m.add_rule(DQRule(name="name_not_null", field="name", check="not_null", params={"default": "anon"}))
        result = m.remediate({"age": 200, "name": None})
        assert result.data == {"age": 120, "name": "anon"}
        assert result.fixes_applied == 2

    def test_remediate_preserves_unrelated_fields(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="age_range", field="age", check="range", params={"min": 0, "max": 120}))
        result = m.remediate({"age": 200, "name": "alice", "tags": ["a", "b"]})
        assert result.data == {"age": 120, "name": "alice", "tags": ["a", "b"]}


# ── Integration: full check + remediate flow ────────────────────────

class TestIntegration:
    def test_detect_then_remediate(self) -> None:
        m = DataQualityMonitor()
        m.add_rule(DQRule(name="age_range", field="age", check="range", params={"min": 0, "max": 120}))
        # First: check (no remediation)
        import asyncio
        check_result = asyncio.run(m.check({"age": 200, "name": "alice"}, dataset="users"))
        # Should have violation
        assert len(check_result["violations"]) >= 1  # type: ignore[arg-type]
        # Then: remediate
        remediated = m.remediate({"age": 200, "name": "alice"})
        assert remediated.data["age"] == 120
        assert remediated.fixes_applied == 1
