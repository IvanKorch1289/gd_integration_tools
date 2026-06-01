"""W25.3 — load_pipeline_from_yaml автоматически мигрирует apiVersion."""

# ruff: noqa: S101

from __future__ import annotations

import yaml

from src.backend.dsl.versioning import CURRENT_VERSION
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def test_loader_migrates_v0_to_current() -> None:
    spec = {
        "apiVersion": "v0",
        "route_id": "test.legacy",
        "processors": [{"log": {"level": "info"}}],
    }
    yaml_str = yaml.safe_dump(spec, sort_keys=False)
    pipeline = load_pipeline_from_yaml(yaml_str)
    out = pipeline.to_dict()
    assert out["apiVersion"] == CURRENT_VERSION
    assert out["route_id"] == "test.legacy"
    assert out["processors"] == [{"log": {"level": "info"}}]


def test_loader_migrates_missing_apiversion_field() -> None:
    spec = {"route_id": "test.no_version"}
    yaml_str = yaml.safe_dump(spec, sort_keys=False)
    pipeline = load_pipeline_from_yaml(yaml_str)
    out = pipeline.to_dict()
    assert out["apiVersion"] == CURRENT_VERSION


def test_loader_passes_through_current_version_without_migration() -> None:
    spec = {
        "apiVersion": CURRENT_VERSION,
        "route_id": "test.modern",
        "processors": [{"log": {"level": "warning"}}],
    }
    yaml_str = yaml.safe_dump(spec, sort_keys=False)
    pipeline = load_pipeline_from_yaml(yaml_str)
    out = pipeline.to_dict()
    assert out["apiVersion"] == CURRENT_VERSION
    # _migrated_from не появляется т.к. миграции не запускались.
    assert "_migrated_from" not in out
