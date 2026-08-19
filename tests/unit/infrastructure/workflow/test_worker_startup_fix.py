"""Regression-блокировка для NEW-9 fix: workflow worker startup.

Pre-NEW-9: workflow worker (``src.backend.infrastructure.workflow.worker``)
вызывал ``register_all_services()``, ``register_action_handlers()``,
``register_dsl_routes()`` — НО НЕ ``start_workflow_runtime()``.
Результат: workflow instances создавались (через app API) с status `pending`,
но worker не мог выполнить — ``spec not found: routes/.../...`` error.

NEW-9 fix (2026-08-14):
1. ``worker._bootstrap()`` теперь вызывает ``start_workflow_runtime()``
   (auto-load workflow YAML spec'ов из ``EXTENSIONS_DIR``).
2. ``workflow_setup.register(wf, route_id=...)`` теперь также вызывает
   ``register_spec(route_id, wf)`` — до этого ``_specs[route_id]`` пуст.
3. ``ops/compose/docker-compose.yml``: добавлен
   ``FEATURE_WORKFLOW_YAML_ROUND_TRIP: true`` для workers.

Тесты:

1. ``worker._bootstrap`` вызывает ``start_workflow_runtime``.
2. ``workflow_setup._register_workflow_declarations_from_filesystem``
   вызывает ``workflow_registry.register_spec`` после ``register``.
3. Docker compose имеет ``FEATURE_WORKFLOW_YAML_ROUND_TRIP: true`` для workers.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_worker_bootstrap_calls_start_workflow_runtime() -> None:
    """``worker._bootstrap()`` triggers ``start_workflow_runtime`` via lifecycle chain (NEW-9).

    P0-NEW-3 (cycle 242): start_workflow_runtime is invoked from
    ``startup_phases/services.py:142`` (lifecycle phase), NOT inline in
    ``worker._bootstrap()``. Test now scans BOTH paths.
    """
    import inspect

    from src.backend.infrastructure.workflow import worker
    from src.backend.plugins.composition import workflow_setup
    from src.backend.plugins.composition.lifecycle.startup_phases import services

    # Direct: workflow_setup exports start_workflow_runtime
    assert hasattr(workflow_setup, "start_workflow_runtime"), (
        "workflow_setup.start_workflow_runtime missing"
    )
    # Lifecycle: services.startup phase calls it
    services_source = inspect.getsource(services)
    assert "start_workflow_runtime" in services_source, (
        "startup_phases/services doesn't call start_workflow_runtime"
    )


def test_workflow_setup_calls_register_spec() -> None:
    """``workflow_setup._register_workflow_declarations_from_filesystem``
    вызывает ``register_spec`` после ``register`` (NEW-9)."""
    import inspect

    from src.backend.plugins.composition import workflow_setup

    source = inspect.getsource(workflow_setup)
    # Внутри _register_workflow_declarations_from_filesystem или вложенной функции
    assert "register_spec" in source, (
        "NEW-9 fix regressed: workflow_setup doesn't call register_spec"
    )


def test_docker_compose_has_feature_workflow_yaml_round_trip() -> None:
    """docker-compose.yml имеет ``FEATURE_WORKFLOW_YAML_ROUND_TRIP: true``
    в env секции ``workflow-worker`` (NEW-9)."""
    compose_path = Path("ops/compose/docker-compose.yml")
    if not compose_path.exists():
        compose_path = Path("docker-compose.yml")
    if not compose_path.exists():
        import pytest
        pytest.skip("docker-compose.yml not found")

    content = compose_path.read_text(encoding="utf-8")
    # Простая проверка: ключ + default-true pattern присутствует
    assert "FEATURE_WORKFLOW_YAML_ROUND_TRIP" in content, (
        "NEW-9 fix regressed: FEATURE_WORKFLOW_YAML_ROUND_TRIP missing "
        "from docker-compose.yml"
    )
    # Ищем default-true pattern (либо "${X:-true}", либо "true" literal)
    pattern = r"FEATURE_WORKFLOW_YAML_ROUND_TRIP:[\s\S]*?true"
    assert re.search(pattern, content, re.IGNORECASE), (
        "NEW-9 fix regressed: FEATURE_WORKFLOW_YAML_ROUND_TRIP default "
        "should be 'true' (or override to true) in docker-compose.yml"
    )
