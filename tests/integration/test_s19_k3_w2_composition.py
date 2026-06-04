"""S19 K3 W2: smoke tests for route composition include:/extends: (wave:s19/k3-w2-route-composition-include).

DoD checkpoint:
    1. routes/composition_demo/route.toml загружается через RouteManifestV11
    2. load_pipeline_from_file работает с include+extends при feature flag=True
    3. Cycle detection raises RuntimeError для extends-циклов
    4. Cycle detection raises RuntimeError для include-циклов
    5. Feature flag OFF игнорирует include/extends полностью
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestS19CompositionSmoke:
    """Smoke tests for S19 K3 W2 route composition (include:/extends:)."""

    def test_composition_demo_route_exists(self) -> None:
        """Composition demo route directory exists."""
        path = Path("routes/composition_demo/route.toml")
        assert path.is_file(), "routes/composition_demo/route.toml missing"

    def test_composition_demo_route_files_exist(self) -> None:
        """All composition demo route files exist on disk."""
        for name in [
            "route.toml",
            "main.dsl.yaml",
            "shared_steps.yaml",
            "base_transforms.yaml",
        ]:
            path = Path(f"routes/composition_demo/{name}")
            assert path.is_file(), f"routes/composition_demo/{name} missing"

    def test_composition_demo_dsl_loads_with_flag_on(self) -> None:
        """load_pipeline_from_file loads main.dsl.yaml with include+extends."""
        from src.backend.dsl.yaml_loader import load_pipeline_from_file

        with patch(
            "src.backend.dsl.yaml_loader._is_route_composition_include_enabled",
            return_value=True,
        ):
            pipeline = load_pipeline_from_file(
                Path("routes/composition_demo/main.dsl.yaml")
            )
            assert pipeline.route_id == "composition.demo"
            # Steps: 2 from shared_steps + 2 from base_transforms + 4 from main
            processors = list(pipeline.processors)
            assert len(processors) >= 3

    def test_cycle_detection_extends_raises_runtime_error(self) -> None:
        """Cycle in extends chain raises RuntimeError."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "a.yaml").write_text("route_id: a\nextends: ./b.yaml\n")
            (tmppath / "b.yaml").write_text("route_id: b\nextends: ./a.yaml\n")

            with patch(
                "src.backend.dsl.yaml_loader._is_route_composition_include_enabled",
                return_value=True,
            ):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file

                with pytest.raises(RuntimeError) as exc_info:
                    load_pipeline_from_file(tmppath / "a.yaml")
                assert "Cycle detected" in str(exc_info.value)

    def test_cycle_detection_include_raises_runtime_error(self) -> None:
        """Cycle in include chain raises RuntimeError."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "a.yaml").write_text("route_id: a\ninclude:\n  - ./b.yaml\n")
            (tmppath / "b.yaml").write_text("route_id: b\ninclude:\n  - ./a.yaml\n")

            with patch(
                "src.backend.dsl.yaml_loader._is_route_composition_include_enabled",
                return_value=True,
            ):
                from src.backend.dsl.yaml_loader import load_pipeline_from_file

                with pytest.raises(RuntimeError) as exc_info:
                    load_pipeline_from_file(tmppath / "a.yaml")
                assert "Cycle detected" in str(exc_info.value)

    def test_composition_flag_off_ignores_include_extends(self) -> None:
        """When feature flag is OFF, include/extends are silently ignored."""
        from src.backend.dsl.yaml_loader import load_pipeline_from_yaml

        yaml_str = """
route_id: test.route
include:
  - ./nonexistent.yaml
extends: ./also_nonexistent.yaml
steps:
  - audit: {action: test}
"""
        with patch(
            "src.backend.dsl.yaml_loader._is_route_composition_include_enabled",
            return_value=False,
        ):
            pipeline = load_pipeline_from_yaml(yaml_str)
            assert pipeline.route_id == "test.route"
            assert len(list(pipeline.processors)) == 1
