"""Regression test: S94 W1 codemod — 6 core/* files use core.logging.

- core/config/consul_config.py
- core/config/hot_reload.py
- core/audit/sinks/ai_unified_sink.py
- core/actions/proto_adapter.py
- core/actions/strawberry_adapter.py
- core/interfaces/__init__.py

Проверяет что import logging → from src.backend.core.logging import get_logger.
Saml_backend, infrastructure/logging/*, dsl/engine/context.py — оставлены
(legit stdlib: Handler classes, type annotations, log backends).
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

TARGETS = (
    "src/backend/core/config/consul_config.py",
    "src/backend/core/config/hot_reload.py",
    "src/backend/core/audit/sinks/ai_unified_sink.py",
    "src/backend/core/actions/proto_adapter.py",
    "src/backend/core/actions/strawberry_adapter.py",
    "src/backend/core/interfaces/__init__.py",
)


@pytest.mark.parametrize("rel_path", TARGETS)
def test_s94_w1_module_uses_core_logger(rel_path: str) -> None:
    src = (PROJECT_ROOT / rel_path).read_text()
    assert "from src.backend.core.logging import get_logger" in src, (
        f"{rel_path} должен использовать core.logging.get_logger"
    )
    assert "import logging" not in src, (
        f"{rel_path} всё ещё использует stdlib logging (S94 W1 missed)"
    )
    assert "logging.getLogger" not in src, (
        f"{rel_path} использует logging.getLogger вместо get_logger"
    )


def test_workflows_worker_keeps_stdlib_for_basicConfig() -> None:
    """workflows/worker.py: keep `import logging` для typer basicConfig.

    S94 W1 explicit: только getLogger() заменяется; basicConfig/logging.WARNING
    constants остаются как stdlib API.
    """
    src = (PROJECT_ROOT / "src/backend/infrastructure/workflow/worker.py").read_text()
    # basicConfig + logging.WARNING — legit stdlib usage
    assert "logging.basicConfig" in src
    # И есть core.logging.get_logger для самого worker
    assert "from src.backend.core.logging import get_logger" in src


def test_dsl_engine_context_keeps_stdlib_for_type() -> None:
    """dsl/engine/context.py: keep `import logging` для type annotation.

    `logger: logging.Logger | None = None` — type annotation использует
    stdlib `logging.Logger`. Заменять нельзя.
    """
    src = (PROJECT_ROOT / "src/backend/dsl/engine/context.py").read_text()
    assert "logging.Logger" in src
    assert "import logging" in src
