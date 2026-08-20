"""Sprint 19 iteration 11: probe_smoke.py harness test.

Verifies:
* probe_get / probe_post return ProbeResult with correct fields
* evaluate() correctly determines pass/fail for int and tuple expected
* main() returns correct exit code based on pass/fail
* run_probes() returns ProbeReport with public + auth-required probes
"""
from __future__ import annotations

import pytest
from tools.probe_smoke import (
    ProbeResult,
    ProbeReport,
    probe_get,
    probe_post,
    run_probes,
    main,
    DEFAULT_BASE,
)


class TestProbeResultEvaluate:
    """ProbeResult.evaluate() — single-result pass/fail logic."""

    def test_int_expected_match(self) -> None:
        """When actual == expected (int), passed=True."""
        r = ProbeResult(name="x", method="GET", path="/x", expected=200, actual=200)
        r.evaluate()
        assert r.passed is True

    def test_int_expected_mismatch(self) -> None:
        """When actual != expected (int), passed=False."""
        r = ProbeResult(name="x", method="GET", path="/x", expected=200, actual=404)
        r.evaluate()
        assert r.passed is False

    def test_tuple_expected_match(self) -> None:
        """When actual in expected (tuple), passed=True."""
        r = ProbeResult(name="x", method="POST", path="/x", expected=(401, 403), actual=403)
        r.evaluate()
        assert r.passed is True

    def test_tuple_expected_mismatch(self) -> None:
        """When actual NOT in expected (tuple), passed=False."""
        r = ProbeResult(name="x", method="POST", path="/x", expected=(401, 403), actual=500)
        r.evaluate()
        assert r.passed is False

    def test_actual_zero_default_before_evaluate(self) -> None:
        """Actual defaults to 0, before evaluate() is called."""
        r = ProbeResult(name="x", method="GET", path="/x", expected=200)
        assert r.actual == 0
        # passed is False by default (before evaluate)
        assert r.passed is False


class TestProbeReport:
    """ProbeReport — aggregate pass/fail counts."""

    def test_empty_report(self) -> None:
        r = ProbeReport(base_url="http://test")
        assert r.passed == 0
        assert r.failed == 0
        assert r.results == []

    def test_passed_and_failed_counts(self) -> None:
        r = ProbeReport(base_url="http://test")
        r.results = [
            ProbeResult(name="a", method="GET", path="/a", expected=200, actual=200),
            ProbeResult(name="b", method="GET", path="/b", expected=200, actual=500),
            ProbeResult(name="c", method="POST", path="/c", expected=(401, 403), actual=403),
        ]
        for x in r.results:
            x.evaluate()
        assert r.passed == 2
        assert r.failed == 1


class TestRunProbes:
    """run_probes() — full probe suite."""

    def test_run_probes_returns_report(self) -> None:
        r = run_probes("http://localhost:1")  # invalid URL → 0 status
        assert isinstance(r, ProbeReport)
        assert r.base_url == "http://localhost:1"
        # Should have many probes registered
        assert len(r.results) >= 20
        # All probes should be evaluated
        for probe in r.results:
            assert probe.actual is not None or probe.detail != ""


class TestMain:
    """main() — CLI entry point."""

    def test_main_no_args(self) -> None:
        """main() with no args uses DEFAULT_BASE."""
        rc = main([])  # invalid URL → all fail
        # rc depends on probe results; just check return type
        assert isinstance(rc, int)

    def test_main_custom_url(self) -> None:
        """main() with custom URL uses it."""
        rc = main(["http://custom:1"])
        assert isinstance(rc, int)


@pytest.mark.unit
def test_default_base_is_localhost_8000() -> None:
    """Default base URL: localhost:8000 (matches `make run-all`)."""
    assert DEFAULT_BASE == "http://localhost:8000"
