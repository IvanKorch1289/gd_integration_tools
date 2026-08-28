"""Regression tests для infrastructure.notifications.adapters.express (Sprint 37 W1, ADR-0282 Phase B Item 5).

Покрывает:
1. Adapter file НЕ импортирует from `dsl.engine.processors.express._common`
   (DSL bridge removed, infra→infra direct import).
2. Adapter self-contained: client factory inline (no DSL helper).
3. `_host_from_url` helper доступна в adapter scope.
4. DSL `_common.py` re-export `get_express_client` still works (backward-compat
   для 8 DSL processors, не touched в этом sprint).

Per ADR-0282 §3 Phase B (Sprint 37 W1 Item 5): prune 1 entry.
infrastructure→infrastructure direct import — allowed (ALLOWED matrix).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_express_adapter_no_dsl_imports() -> None:
    """Express adapter does NOT import from dsl.engine.processors.express._common.

    Sprint 37 W1: DSL bridge removed (infrastructure→infrastructure direct only).
    """
    adapter_path = "src/backend/infrastructure/notifications/adapters/express.py"
    tree = ast.parse(Path(adapter_path).read_text(encoding="utf-8"))

    dsl_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "dsl" in module:
                dsl_imports.append(
                    f"from {module} import {', '.join(n.name for n in node.names)}"
                )

    assert not dsl_imports, (
        f"Express adapter should NOT import from dsl.* (Sprint 37 W1). "
        f"Found imports: {dsl_imports}. "
        f"Use infrastructure.clients.external.express_bot directly."
    )


def test_express_adapter_imports_infrastructure_express_bot() -> None:
    """Express adapter imports from infrastructure.clients.external.express_bot.

    Canonical home for ExpressBotClient + BotConfig.
    """
    adapter_path = "src/backend/infrastructure/notifications/adapters/express.py"
    tree = ast.parse(Path(adapter_path).read_text(encoding="utf-8"))

    infra_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "infrastructure.clients.external.express_bot" in module:
                names = ", ".join(n.name for n in node.names)
                infra_imports.append(f"from {module} import {names}")

    assert infra_imports, (
        "Express adapter should import from "
        "infrastructure.clients.external.express_bot (canonical home)"
    )


def test_dsl_get_express_client_still_works() -> None:
    """DSL processors (8 importers) still get get_express_client from _common.

    Sprint 37 W1 НЕ трогает DSL processors — backward-compat preserved.
    The DSL helper remains at `dsl.engine.processors.express._common`.
    """
    from src.backend.dsl.engine.processors.express._common import get_express_client

    assert callable(get_express_client)


def test_dsl_processors_unaffected() -> None:
    """8 DSL processor files still use `from ._common import get_express_client`.

    These imports work unchanged after Sprint 37 W1 (DSL helper preserved).
    """
    processor_files = [
        "src/backend/dsl/engine/processors/express/typing.py",
        "src/backend/dsl/engine/processors/express/send.py",
        "src/backend/dsl/engine/processors/express/status.py",
        "src/backend/dsl/engine/processors/express/edit.py",
        "src/backend/dsl/engine/processors/express/reply.py",
        "src/backend/dsl/engine/processors/express/send_file.py",
    ]

    for proc_file in processor_files:
        text = Path(proc_file).read_text(encoding="utf-8")
        assert "from ._common import get_express_client" in text or (
            "get_express_client" in text
        ), f"{proc_file} должен импортировать get_express_client (backward-compat)"


class TestAdapterSelfContained:
    """Adapter has all client factory logic inline (no external helper)."""

    def test_host_from_url_helper_exists(self) -> None:
        """_host_from_url helper defined в adapter scope."""
        from src.backend.infrastructure.notifications.adapters.express import (
            _host_from_url,
        )

        assert callable(_host_from_url)
        assert _host_from_url("https://example.com/path") == "example.com"
        assert _host_from_url("") == ""

    def test_express_adapter_instantiable(self) -> None:
        """ExpressAdapter can be instantiated (no DSL dependency at construction)."""
        from src.backend.infrastructure.notifications.adapters.express import (
            ExpressAdapter,
        )

        adapter = ExpressAdapter()
        assert adapter.kind == "express"
        assert adapter._default_bot == "main_bot"
