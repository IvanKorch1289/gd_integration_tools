"""Tests for ``core.docs_generator`` CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.backend.core.docs_generator.generator import cli_main


class TestCliMain:
    def test_help_exits_1_without_subcommand(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["docs_generator"]):
                cli_main()
        assert exc_info.value.code == 2

    def test_registry_explorers_writes_files(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "docs"
        with patch.object(
            sys,
            "argv",
            [
                "docs_generator",
                "generate",
                "--registry-explorers",
                "--output",
                str(out_dir),
            ],
        ):
            rc = cli_main()
        assert rc == 0
        # Three sections written.
        assert (out_dir / "routes" / "index.md").exists()
        assert (out_dir / "connectors" / "index.md").exists()
        assert (out_dir / "actions" / "index.md").exists()
        # Top-level index.md.
        assert (out_dir / "index.md").exists()

    def test_sla_cockpit(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "sla_docs"
        with patch.object(
            sys,
            "argv",
            ["docs_generator", "generate", "--sla-cockpit", "--output", str(out_dir)],
        ):
            rc = cli_main()
        assert rc == 0
        assert (out_dir / "sla" / "index.md").exists()

    def test_cdc_control_plane(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "cdc_docs"
        with patch.object(
            sys,
            "argv",
            [
                "docs_generator",
                "generate",
                "--cdc-control-plane",
                "--output",
                str(out_dir),
            ],
        ):
            rc = cli_main()
        assert rc == 0
        assert (out_dir / "cdc" / "index.md").exists()

    def test_no_section_fails(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        with patch.object(
            sys, "argv", ["docs_generator", "generate", "--output", str(out_dir)]
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_main()
        # argparse.parser.error exits with code 2.
        assert exc_info.value.code == 2
