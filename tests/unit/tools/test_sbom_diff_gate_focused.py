"""Focused tests for ``tools/checks/sbom_diff_gate`` (Wave OP-3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.checks.sbom_diff_gate import (
    DEFAULT_DENY_LICENSES,
    SBOMComponent,
    SBOMDiff,
    _parse_components,
    diff_sboms,
    main,
)


def _write_sbom(path: Path, components: list[dict]) -> Path:
    """Helper: write CycloneDX-like SBOM file."""
    data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "components": components,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def temp_sboms(tmp_path: Path):
    """Sample SBOMs для тестов."""
    sbom_a = tmp_path / "sbom_a.cdx.json"
    sbom_b = tmp_path / "sbom_b.cdx.json"

    _write_sbom(
        sbom_a,
        [
            {
                "name": "fastapi",
                "version": "0.100.0",
                "purl": "pkg:pypi/fastapi@0.100.0",
                "licenses": [{"license": {"id": "MIT"}}],
            },
            {
                "name": "pydantic",
                "version": "2.5.0",
                "purl": "pkg:pypi/pydantic@2.5.0",
                "licenses": [{"license": {"id": "MIT"}}],
            },
        ],
    )
    return {"a": sbom_a, "b": sbom_b}


class TestSBOMComponent:
    def test_init(self) -> None:
        c = SBOMComponent(name="x", version="1.0", licenses=["MIT"])
        assert c.name == "x"
        assert c.version == "1.0"
        assert c.licenses == ["MIT"]
        assert c.purl == ""


class TestParseComponents:
    def test_parse_basic(self, tmp_path: Path) -> None:
        sbom = tmp_path / "test.cdx.json"
        _write_sbom(
            sbom,
            [
                {
                    "name": "fastapi",
                    "version": "0.100.0",
                    "purl": "pkg:pypi/fastapi@0.100.0",
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
        )
        components = _parse_components(sbom)
        assert len(components) == 1
        assert components[0].name == "fastapi"
        assert components[0].version == "0.100.0"
        assert components[0].licenses == ["MIT"]

    def test_parse_missing_license(self, tmp_path: Path) -> None:
        sbom = tmp_path / "test.cdx.json"
        _write_sbom(
            sbom,
            [
                {
                    "name": "mystery",
                    "version": "1.0",
                    "purl": "pkg:pypi/mystery@1.0",
                }
            ],
        )
        components = _parse_components(sbom)
        assert components[0].licenses == []

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _parse_components(tmp_path / "missing.cdx.json")
        assert exc_info.value.code == 2

    def test_parse_invalid_json(self, tmp_path: Path) -> None:
        sbom = tmp_path / "bad.cdx.json"
        sbom.write_text("not json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            _parse_components(sbom)
        assert exc_info.value.code == 2


class TestDiffSBOMs:
    def test_no_changes(self) -> None:
        comps = [
            SBOMComponent(name="x", version="1.0", licenses=["MIT"])
        ]
        diff = diff_sboms(current=comps, baseline=comps)
        assert diff.added == []
        assert diff.removed == []
        assert diff.license_violations == []
        assert not diff.has_violations

    def test_added_component(self) -> None:
        current = [
            SBOMComponent(name="x", version="1.0", licenses=["MIT"]),
            SBOMComponent(name="y", version="2.0", licenses=["MIT"]),
        ]
        baseline = [
            SBOMComponent(name="x", version="1.0", licenses=["MIT"]),
        ]
        diff = diff_sboms(current=current, baseline=baseline)
        assert len(diff.added) == 1
        assert diff.added[0].name == "y"
        assert len(diff.removed) == 0
        assert diff.delta_components == 1

    def test_removed_component(self) -> None:
        current = [
            SBOMComponent(name="x", version="1.0", licenses=["MIT"]),
        ]
        baseline = [
            SBOMComponent(name="x", version="1.0", licenses=["MIT"]),
            SBOMComponent(name="y", version="2.0", licenses=["MIT"]),
        ]
        diff = diff_sboms(current=current, baseline=baseline)
        assert len(diff.added) == 0
        assert len(diff.removed) == 1
        assert diff.removed[0].name == "y"
        assert diff.delta_components == -1

    def test_license_violation_gpl(self) -> None:
        current = [
            SBOMComponent(name="evil", version="1.0", licenses=["GPL-3.0"]),
        ]
        baseline: list[SBOMComponent] = []
        diff = diff_sboms(current=current, baseline=baseline)
        assert len(diff.license_violations) == 1
        assert diff.license_violations[0][0] == "GPL-3.0"
        assert diff.license_violations[0][1].name == "evil"
        assert diff.has_violations is True

    def test_license_violation_agpl(self) -> None:
        current = [
            SBOMComponent(name="x", version="1.0", licenses=["AGPL-3.0"]),
        ]
        diff = diff_sboms(current=current, baseline=[])
        assert len(diff.license_violations) == 1
        assert diff.has_violations is True

    def test_unknown_license_flagged(self) -> None:
        current = [
            SBOMComponent(name="x", version="1.0", licenses=[]),
        ]
        diff = diff_sboms(current=current, baseline=[])
        assert len(diff.unknown_licenses) == 1
        assert diff.unknown_licenses[0].name == "x"
        assert diff.has_violations is True

    def test_mit_components_pass(self) -> None:
        current = [
            SBOMComponent(name="fastapi", version="0.100", licenses=["MIT"]),
            SBOMComponent(name="pydantic", version="2.5", licenses=["MIT"]),
            SBOMComponent(name="apache-lib", version="1.0", licenses=["Apache-2.0"]),
        ]
        diff = diff_sboms(current=current, baseline=[])
        assert not diff.has_violations

    def test_custom_deny_list(self) -> None:
        """Custom deny list (e.g., JSON-license rejected)."""
        current = [
            SBOMComponent(name="x", version="1.0", licenses=["JSON"]),
        ]
        diff = diff_sboms(
            current=current,
            baseline=[],
            deny_licenses=frozenset({"JSON"}),
        )
        assert diff.has_violations

    def test_default_deny_list_includes_gpl_agpl(self) -> None:
        """Default deny list содержит GPL/AGPL/SSPL/BUSL."""
        assert "GPL-3.0" in DEFAULT_DENY_LICENSES
        assert "AGPL-3.0" in DEFAULT_DENY_LICENSES
        assert "SSPL-1.0" in DEFAULT_DENY_LICENSES
        assert "BUSL-1.1" in DEFAULT_DENY_LICENSES


class TestDiffReport:
    def test_report_pass(self, capsys) -> None:
        from tools.checks.sbom_diff_gate import _format_report

        diff = SBOMDiff(
            added=[SBOMComponent("x", "1.0", licenses=["MIT"])],
            total_components=1,
            delta_components=1,
        )
        report = _format_report(diff)
        assert "RESULT: PASS" in report

    def test_report_fail(self) -> None:
        from tools.checks.sbom_diff_gate import _format_report

        diff = SBOMDiff(
            license_violations=[
                ("GPL-3.0", SBOMComponent("evil", "1.0", licenses=["GPL-3.0"])),
            ],
            total_components=1,
        )
        report = _format_report(diff)
        assert "RESULT: FAIL" in report
        assert "GPL-3.0" in report

    def test_report_added_components(self) -> None:
        from tools.checks.sbom_diff_gate import _format_report

        diff = SBOMDiff(
            added=[
                SBOMComponent("new1", "1.0", licenses=["MIT"]),
                SBOMComponent("new2", "2.0", licenses=["MIT"]),
            ],
            total_components=2,
            delta_components=2,
        )
        report = _format_report(diff)
        assert "ADDED" in report
        assert "+ new1" in report
        assert "+ new2" in report


class TestCLI:
    def test_cli_pass(self, temp_sboms, tmp_path, capsys) -> None:
        """CLI returns 0 когда нет violations."""
        # Same SBOM for current and baseline.
        current_path = temp_sboms["a"]
        baseline_path = tmp_path / "baseline.cdx.json"
        baseline_path.write_text(current_path.read_text())

        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(current_path),
            "--baseline",
            str(baseline_path),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "RESULT: PASS" in captured.out

    def test_cli_fail_license_violation(self, temp_sboms, tmp_path) -> None:
        """CLI returns 1 при license violation."""
        # Current с GPL.
        current_path = tmp_path / "current.cdx.json"
        _write_sbom(
            current_path,
            [
                {
                    "name": "evil",
                    "version": "1.0",
                    "purl": "pkg:pypi/evil@1.0",
                    "licenses": [{"license": {"id": "GPL-3.0"}}],
                }
            ],
        )
        baseline_path = tmp_path / "baseline.cdx.json"
        _write_sbom(baseline_path, [])

        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(current_path),
            "--baseline",
            str(baseline_path),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        assert exit_code == 1

    def test_cli_threshold_exceeded(self, temp_sboms, tmp_path) -> None:
        """CLI returns 1 если new components > threshold."""
        current_path = tmp_path / "current.cdx.json"
        _write_sbom(
            current_path,
            [
                {"name": f"x{i}", "version": "1.0", "licenses": [{"license": {"id": "MIT"}}]}
                for i in range(10)
            ],
        )
        baseline_path = tmp_path / "baseline.cdx.json"
        _write_sbom(baseline_path, [])

        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(current_path),
            "--baseline",
            str(baseline_path),
            "--threshold-new-components",
            "5",
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        assert exit_code == 1

    def test_cli_missing_sbom(self, tmp_path) -> None:
        """CLI returns 2 при missing current SBOM."""
        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(tmp_path / "missing.cdx.json"),
            "--baseline",
            str(tmp_path / "baseline.cdx.json"),
        ]
        try:
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
        finally:
            sys.argv = old_argv

    def test_cli_update_baseline(self, temp_sboms, tmp_path) -> None:
        """CLI --update-baseline copies current to baseline."""
        current_path = tmp_path / "current.cdx.json"
        _write_sbom(
            current_path,
            [
                {"name": "x", "version": "1.0", "licenses": [{"license": {"id": "MIT"}}]}
            ],
        )
        baseline_path = tmp_path / "baseline.cdx.json"
        _write_sbom(baseline_path, [])

        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(current_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
        ]
        try:
            main()
        finally:
            sys.argv = old_argv

        # Baseline теперь равен current.
        assert baseline_path.read_text() == current_path.read_text()

    def test_cli_first_run_no_baseline(self, tmp_path, capsys) -> None:
        """CLI first run без baseline — warn + empty diff."""
        current_path = tmp_path / "current.cdx.json"
        _write_sbom(
            current_path,
            [
                {"name": "x", "version": "1.0", "licenses": [{"license": {"id": "MIT"}}]}
            ],
        )
        baseline_path = tmp_path / "missing_baseline.cdx.json"

        import sys
        old_argv = sys.argv
        sys.argv = [
            "sbom_diff_gate",
            "--current",
            str(current_path),
            "--baseline",
            str(baseline_path),
        ]
        try:
            exit_code = main()
        finally:
            sys.argv = old_argv

        # First run = empty baseline → no violations.
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Baseline не найден" in captured.err or "first run" in captured.err.lower()


class TestRealisticExample:
    """Realistic: detect copyleft в incoming dep."""

    def test_gpl_dependency_caught(self) -> None:
        """New dependency с GPL license caught by gate."""
        current = [
            SBOMComponent(name="legacy-gpl-lib", version="1.0", licenses=["GPL-3.0"]),
        ]
        baseline: list[SBOMComponent] = []
        diff = diff_sboms(current=current, baseline=baseline)
        assert diff.has_violations
        assert any("GPL" in lic for lic, _ in diff.license_violations)

    def test_mixed_licenses(self) -> None:
        """Mixed MIT + GPL: только GPL flagged."""
        current = [
            SBOMComponent(name="good", version="1.0", licenses=["MIT"]),
            SBOMComponent(name="bad", version="1.0", licenses=["GPL-3.0"]),
            SBOMComponent(name="apache", version="1.0", licenses=["Apache-2.0"]),
        ]
        diff = diff_sboms(current=current, baseline=[])
        assert len(diff.license_violations) == 1
        assert diff.license_violations[0][1].name == "bad"
