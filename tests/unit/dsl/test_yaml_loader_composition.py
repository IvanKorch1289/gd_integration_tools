"""Tests for YAML loader include:/extends: composition (S19 K3 W2)."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


class TestIncludeExtends:
    """K3 S19 W2: route composition via include:/extends: with cycle detection."""

    def test_cycle_detection_extends_raises_runtime_error(self) -> None:
        """Cycle in extends chain should raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create files that reference each other (cycle)
            (tmppath / "a.yaml").write_text('route_id: a\nextends: ./b.yaml\n')
            (tmppath / "b.yaml").write_text('route_id: b\nextends: ./a.yaml\n')

            with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file
                with pytest.raises(RuntimeError) as exc_info:
                    load_pipeline_from_file(tmppath / "a.yaml")
                assert "Cycle detected" in str(exc_info.value)

    def test_cycle_detection_include_raises_runtime_error(self) -> None:
        """Cycle in include chain should raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create files that reference each other (cycle)
            (tmppath / "a.yaml").write_text('route_id: a\ninclude:\n  - ./b.yaml\n')
            (tmppath / "b.yaml").write_text('route_id: b\ninclude:\n  - ./a.yaml\n')

            with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file
                with pytest.raises(RuntimeError) as exc_info:
                    load_pipeline_from_file(tmppath / "a.yaml")
                assert "Cycle detected" in str(exc_info.value)

    def test_composition_flag_off_ignores_include_extends(self) -> None:
        """When feature flag is OFF, include/extends are ignored."""
        yaml_str = """
route_id: test.route
include:
  - ./nonexistent.yaml
extends: ./also_nonexistent.yaml
steps:
  - audit: {event: test}
"""
        with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=False):
            pipeline = load_pipeline_from_yaml(yaml_str)
            assert pipeline.route_id == "test.route"
            assert len(list(pipeline.processors)) == 1

    def test_include_loads_steps_from_other_file(self) -> None:
        """Include: should load and append steps from other YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create shared steps file
            (tmppath / "shared.yaml").write_text("""
route_id: shared.route
steps:
  - audit: {event: shared.start}
  - proxy: {src: /shared, dst: http://shared:8080}
""")

            # Create main file that includes shared
            (tmppath / "main.yaml").write_text("""
route_id: main.route
include:
  - ./shared.yaml
steps:
  - call_function: {ref: extensions.main:handler}
""")

            with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file
                pipeline = load_pipeline_from_file(tmppath / "main.yaml")
                assert pipeline.route_id == "main.route"
                # Should have 3 steps: 2 from shared + 1 from main
                processors = list(pipeline.processors)
                assert len(processors) == 3

    def test_extends_loads_and_merges_base_route(self) -> None:
        """Extends: should load base and merge with child."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create base file
            (tmppath / "base.yaml").write_text("""
route_id: base.route
source: timer:60s
description: Base route description
steps:
  - proxy: {src: /api/base, dst: http://base:8080}
  - audit: {event: base.called}
""")

            # Create child that extends base
            (tmppath / "child.yaml").write_text("""
route_id: child.route
extends: ./base.yaml
description: Child route override
steps:
  - call_function: {ref: extensions.foo:bar}
""")

            with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file
                pipeline = load_pipeline_from_file(tmppath / "child.yaml")
                # Child route_id should be used
                assert pipeline.route_id == "child.route"
                # Should have 3 steps: 2 from base + 1 from child
                processors = list(pipeline.processors)
                assert len(processors) == 3

    def test_self_reference_cycle_detection(self) -> None:
        """File that extends/ includes itself should raise error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create self-referencing file
            (tmppath / "self.yaml").write_text("""
route_id: self.route
extends: ./self.yaml
""")

            with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file
                with pytest.raises(RuntimeError) as exc_info:
                    load_pipeline_from_file(tmppath / "self.yaml")
                assert "Cycle detected" in str(exc_info.value)

    def test_missing_included_file_raises_file_not_found(self) -> None:
        """Include of nonexistent file should raise FileNotFoundError."""
        yaml_str = """
route_id: test.route
include:
  - ./nonexistent.yaml
steps:
  - audit: {event: test}
"""
        with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
            with pytest.raises(FileNotFoundError) as exc_info:
                load_pipeline_from_yaml(yaml_str)
            assert "Included YAML file not found" in str(exc_info.value)

    def test_missing_extended_file_raises_file_not_found(self) -> None:
        """Extends of nonexistent file should raise FileNotFoundError."""
        yaml_str = """
route_id: test.route
extends: ./nonexistent.yaml
steps:
  - audit: {event: test}
"""
        with patch('src.backend.dsl.yaml_loader._is_route_composition_include_enabled', return_value=True):
            with pytest.raises(FileNotFoundError) as exc_info:
                load_pipeline_from_yaml(yaml_str)
            assert "Extended YAML file not found" in str(exc_info.value)
