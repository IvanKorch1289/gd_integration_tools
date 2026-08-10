"""Architecture ratchet (P1 S172 W2) — frontend boundary.

Запрещает новые прямые импорты ``src.backend.*`` (за пределами approved
facade/client boundary) в ``src/frontend/streamlit_app``.

Approved boundary:
- ``src.backend.core.api`` — canonical public API facade (cycle 29 P1-#1)
- ``src.backend.core.frontend_facade`` — legacy facade (streamlit ↔ core)

Запрещены:
- ``src.backend.infrastructure.*``
- ``src.backend.services.*``
- ``src.backend.dsl.*``
- ``src.backend.entrypoints.*``
- ``src.backend.workflow.*``
- любые другие ``src.backend.*`` (включая ``src.backend.core.X``, кроме facade)

При появлении violation — добавить domain-client method в
``src/frontend/streamlit_app/api_clients/`` и/или расширить facade
(``src.backend.core.api`` / ``src.backend.core.frontend_facade``).

CI: enqueue через ``make arch-ratchet`` (см. ``make/quality.mk``).
"""


from __future__ import annotations

import os
import re

import pytest

# Approved facade boundary (P1 S172 W2).
ALLOWED_FACADES: frozenset[str] = frozenset(
    {
        "src.backend.core.api",
        "src.backend.core.frontend_facade",
    },
)

# Top-level запрещённые слои (architectural layers).
FORBIDDEN_TOP_LEVELS: tuple[str, ...] = (
    "src.backend.infrastructure",
    "src.backend.services",
    "src.backend.dsl",
    "src.backend.entrypoints",
    "src.backend.workflow",
)


def _walk_python_files(root: str):
    """Yield all .py files under root, skipping __pycache__."""
    for dirpath, dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _is_allowed_facade(module: str) -> bool:
    """Return True if module is in the approved facade boundary."""
    return module in ALLOWED_FACADES or any(
        module.startswith(prefix + ".") for prefix in ALLOWED_FACADES
    )


class TestFrontendLayerBoundaryRatchet:
    """Architectural ratchet: frontend → backend только через approved facade."""

    def test_no_direct_imports_to_upper_layers(self) -> None:
        """Top-level architectural layers не импортируются напрямую из frontend."""
        frontend_root = "src/frontend/streamlit_app"
        if not os.path.exists(frontend_root):
            pytest.skip("frontend root not found")

        violations: list[tuple[str, str]] = []
        for p in _walk_python_files(frontend_root):
            with open(p) as fp:
                content = fp.read()
            for forbidden in FORBIDDEN_TOP_LEVELS:
                pattern = re.compile(
                    rf"from {re.escape(forbidden)}(?:\b|\.)"
                    rf"|import {re.escape(forbidden)}(?:\b|\.)",
                )
                for m in pattern.finditer(content):
                    violations.append((p, m.group(0)))

        assert not violations, (
            f"Frontend => upper-layer нарушений: {len(violations)}; "
            f"sample: {violations[:5]}"
        )

    def test_only_approved_facades_used(self) -> None:
        """Любые src.backend.* импорты в frontend — только через approved facade.

        Ловит обе формы: ``from src.backend.X import ...`` и
        ``import src.backend.X``.
        """
        frontend_root = "src/frontend/streamlit_app"
        if not os.path.exists(frontend_root):
            pytest.skip("frontend root not found")

        violations: list[tuple[str, str]] = []
        for p in _walk_python_files(frontend_root):
            with open(p) as fp:
                content = fp.read()
            # Unified: catches both 'from src.backend.X' and 'import src.backend.X'.
            matches = re.findall(
                r"(?:from|import)\s+(src\.backend\.[\w\.]+)", content,
            )
            for mod in matches:
                if _is_allowed_facade(mod):
                    continue
                violations.append((p, mod))

        assert not violations, (
            f"Frontend нарушений facade boundary: {len(violations)}; "
            f"sample: {violations[:5]}"
        )


class TestApiClientsBoundaryRatchet:
    """api_clients/ — особенно строгий контракт: thin client + facade only."""

    def test_api_clients_only_use_facade(self) -> None:
        """api_clients/*.py импортирует только facade-layer (allow-list).

        Ловит обе формы: ``from src.backend.X import ...`` и
        ``import src.backend.X``.
        """
        api_dir = "src/frontend/streamlit_app/api_clients"
        if not os.path.isdir(api_dir):
            pytest.skip("api_clients directory not found")

        violations: list[tuple[str, str]] = []
        for f in sorted(os.listdir(api_dir)):
            if not f.endswith(".py") or f.startswith("_") or f == "__init__.py":
                continue
            p = os.path.join(api_dir, f)
            with open(p) as fp:
                content = fp.read()
            # Unified: catches both 'from' and 'import' styles.
            matches = re.findall(
                r"(?:from|import)\s+(src\.backend\.[\w\.]+)", content,
            )
            for mod in matches:
                if _is_allowed_facade(mod):
                    continue
                violations.append((p, mod))

        assert not violations, (
            f"api_clients/ имеет {len(violations)} обходных импортов: "
            f"{violations[:5]} "
            f"(Approved: {sorted(ALLOWED_FACADES)})"
        )

    def test_api_clients_no_upper_layer_imports(self) -> None:
        """api_clients/ не должен импортировать infrastructure/services/dsl напрямую."""
        api_dir = "src/frontend/streamlit_app/api_clients"
        if not os.path.isdir(api_dir):
            pytest.skip("api_clients directory not found")

        violations: list[tuple[str, str]] = []
        for f in sorted(os.listdir(api_dir)):
            if not f.endswith(".py") or f.startswith("_") or f == "__init__.py":
                continue
            p = os.path.join(api_dir, f)
            with open(p) as fp:
                content = fp.read()
            for forbidden in FORBIDDEN_TOP_LEVELS:
                pattern = re.compile(
                    rf"from {re.escape(forbidden)}(?:\b|\.)"
                    rf"|import {re.escape(forbidden)}(?:\b|\.)",
                )
                for m in pattern.finditer(content):
                    violations.append((p, m.group(0)))

        assert not violations, (
            f"api_clients/ upper-layer импортов: {len(violations)}; "
            f"sample: {violations[:5]}"
        )


class TestRatchetIntegrated:
    """Ratchet покрыт CI через ``make arch-ratchet``."""

    def test_make_arch_ratchet_target_exists(self) -> None:
        """Makefile target ``arch-ratchet`` определён (в sub-make)."""
        # Target регистрируется в make/quality.mk (sub-make), но должен быть
        # виден через root Makefile PHONY list.
        with open("Makefile") as f:
            mf_content = f.read()
        with open("make/quality.mk") as f:
            qm_content = f.read()
        assert "arch-ratchet" in mf_content, (
            "Makefile PHONY list contains 'arch-ratchet' — expected"
        )
        assert "arch-ratchet:" in qm_content, (
            "make/quality.mk target 'arch-ratchet:' missing"
        )

    def test_make_arch_ratchet_uses_pytest(self) -> None:
        """``make arch-ratchet`` запускает pytest ratchet-тесты."""
        with open("make/quality.mk") as f:
            content = f.read()
        assert "arch-ratchet:" in content, (
            "make/quality.mk target 'arch-ratchet' missing"
        )
        # Должен вызывать pytest с ratchet-тестами.
        assert "pytest" in content and (
            "test_layer_boundary" in content or "test_arch_ratchet" in content
        ), (
            "make/quality.mk 'arch-ratchet' не вызывает ratchet-тесты"
        )
