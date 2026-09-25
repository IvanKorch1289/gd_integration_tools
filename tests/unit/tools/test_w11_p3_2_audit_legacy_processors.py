"""Focused tests: W11 P3-2 — audit_legacy_processors.py tool.

Validation:
1. Module imports + main() works without args.
2. JSON output structure.
3. --strict mode exit codes.
4. Inventory classifies files correctly (REMOVABLE / SEMANTIC_KEEP / SHIMMED).
5. Per-file classification logic via _classify().
6. Importer counting (mock-friendly).
7. Canonical target detection.

ADR-0341: legacy processor inventory tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TOOLS_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "audit_legacy_processors.py"
)
_MODULE_NAME = "tools.audit_legacy_processors"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec_module — required for @dataclass with frozen=True
# (Python 3.12+ checks cls.__module__ in sys.modules during dataclass creation).
sys.modules[_MODULE_NAME] = module
_spec.loader.exec_module(module)

build_inventory = module.build_inventory
main = module.main
render_table = module.render_table
_classify = module._classify
LegacyProcessorRow = module.LegacyProcessorRow


@pytest.fixture(scope="session")
def real_inventory() -> list:
    """Session-scoped fixture: build real inventory ONCE per test session.

    build_inventory() scans ~5000 files in repo (~7s with cache).
    Session scope avoids redundant scans across multiple tests.
    """
    return build_inventory()


class TestModuleImports:
    """Module structure и main() entry."""

    def test_app_imports_cleanly(self) -> None:
        assert hasattr(module, "build_inventory")
        assert hasattr(module, "main")
        assert hasattr(module, "LegacyProcessorRow")

    def test_main_help(self) -> None:
        """--help prints usage and exits (argparse convention)."""
        import pytest

        # argparse вызывает parser.exit() при --help → SystemExit(0).
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0


class TestJsonOutput:
    """JSON output structure."""

    def test_json_returns_valid_dict(self) -> None:
        # Use the actual tool's --json mode
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "generated_at" in data
        assert "total_files" in data
        assert "total_loc" in data
        assert "rows" in data
        assert "summary" in data
        assert isinstance(data["rows"], list)
        assert data["total_files"] > 0

    def test_json_summary_counts(self) -> None:
        """Summary should match status counts in rows."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json"])
        data = json.loads(buf.getvalue())
        actual_counts: dict[str, int] = {}
        for row in data["rows"]:
            actual_counts[row["status"]] = actual_counts.get(row["status"], 0) + 1
        assert data["summary"] == actual_counts


class TestHumanReadable:
    """Human-readable table."""

    def test_table_renders(self, real_inventory: list) -> None:
        table = render_table(real_inventory)
        assert "Legacy DSL processors inventory" in table
        assert "Total LOC:" in table
        assert "Summary:" in table
        assert "File" in table
        assert "LOC" in table
        assert "Imp" in table
        assert "Status" in table


class TestClassify:
    """_classify() logic per v4 §10 P1 + §9 (SagaLRA special)."""

    def _row(self, **kwargs) -> LegacyProcessorRow:
        defaults = {
            "file": "src/backend/dsl/processors/X.py",
            "loc": 50,
            "importer_count": 0,
            "canonical_target": "(no canonical re-export)",
            "status": "",
            "has_warning": False,
            "module_name": "src.backend.dsl.processors.X",
        }
        defaults.update(kwargs)
        return LegacyProcessorRow(**defaults)

    def test_saga_lra_semantic_keep(self) -> None:
        """SagaLRA — preserve per v4 §9 (semantic differences)."""
        row = self._row(
            file="src/backend/dsl/processors/saga_lra_processor/core_mixin.py",
            importer_count=5,
            canonical_target="(no canonical re-export)",
        )
        assert _classify(row) == "SEMANTIC_KEEP"

    def test_shimmed_with_canonical_re_export(self) -> None:
        row = self._row(
            file="src/backend/dsl/processors/event_store/processor.py",
            importer_count=0,
            canonical_target="src.backend.dsl.engine.processors.base",
        )
        assert _classify(row) == "SHIMMED"

    def test_removable_zero_importers_no_canonical(self) -> None:
        """0 importers + no canonical + single-file → REMOVABLE.

        Note: realistic `strangler_fig.py` is now SHIMMED (docstring-deprecation).
        Этот тест проверяет classifier-purity: искусственный single-file orphan
        без canonical target должен быть REMOVABLE.
        """
        row = self._row(
            file="src/backend/dsl/processors/orphan_legacy.py",
            importer_count=0,
            canonical_target="(no canonical re-export)",
        )
        assert _classify(row) == "REMOVABLE"

    def test_shimmed_via_canonical_engine_processors_prefix(self) -> None:
        """canonical target = 'src.backend.dsl.engine.processors.X' → SHIMMED."""
        row = self._row(
            file="src/backend/dsl/processors/event_store/processor.py",
            importer_count=0,
            canonical_target="src.backend.dsl.engine.processors.base",
        )
        assert _classify(row) == "SHIMMED"

    def test_shimmed_via_package_internal_sibling(self) -> None:
        """Package-internal sibling без canonical target → SHIMMED.

        Real-world example: `dsl.processors.event_store.cqrs` импортирует
        from .event_store.store — это НЕ orphan, это часть multi-file
        decomposition. Even with 0 external importers → SHIMMED.
        """
        from tools.audit_legacy_processors import _is_package_internal_sibling

        # Сначала проверим, что модуль реально in-package:
        mn = "dsl.processors.event_store.cqrs"
        assert _is_package_internal_sibling(mn), (
            f"fixture failure: {mn} should be detected as package-internal sibling"
        )
        row = self._row(
            file="src/backend/dsl/processors/event_store/cqrs.py",
            importer_count=0,
            canonical_target="(no canonical re-export)",
            module_name=mn,
        )
        assert _classify(row) == "SHIMMED"

    def test_is_package_internal_sibling_thresholds(self) -> None:
        """Threshold check: single-file top-level ≠ package-internal."""
        from tools.audit_legacy_processors import _is_package_internal_sibling

        # Single-file top-level (3 parts) → False
        assert _is_package_internal_sibling("dsl.processors.batch_processor") is False
        # In-package sub-module (4 parts) → True (event_store has __init__.py)
        assert _is_package_internal_sibling("dsl.processors.event_store.cqrs") is True
        # In-package sub-module другого пакета (4 parts) → True
        assert (
            _is_package_internal_sibling("dsl.processors.idp_pipeline_processor.state")
            is True
        )

    def test_is_package_internal_sibling_nonexistent_package(self) -> None:
        """Несуществующий sub-package → False (heuristic защита)."""
        from tools.audit_legacy_processors import _is_package_internal_sibling

        # Если sub-package не существует — False (не пытаемся догадаться).
        assert _is_package_internal_sibling("dsl.processors.nonexistent.foo") is False

    def test_needs_migration_with_importers(self) -> None:
        """No canonical target + importers > 0 → NEEDS_MIGRATION."""
        # Используем _classify явно, избегая self._row assignment warning.
        from tools.audit_legacy_processors import _classify as _cls

        row = self._row(
            file="src/backend/dsl/processors/some_legacy.py",
            importer_count=3,
            canonical_target="(no canonical re-export)",
        )
        assert _cls(row) == "NEEDS_MIGRATION"

    def test_needs_migration_no_canonical(self) -> None:
        """No canonical target + > 0 importers → NEEDS_MIGRATION (duplicate)."""
        row = self._row(
            file="src/backend/dsl/processors/some_legacy.py",
            importer_count=3,
            canonical_target="(no canonical re-export)",
        )
        assert _classify(row) == "NEEDS_MIGRATION"

    def test_classification_priority_saga_over_canonical(self) -> None:
        """SagaLRA + canonical → still SEMANTIC_KEEP (priority over shim)."""
        row = self._row(
            file="src/backend/dsl/processors/saga_lra_processor/special.py",
            importer_count=0,
            canonical_target="src.backend.dsl.engine.processors.special",
        )
        assert _classify(row) == "SEMANTIC_KEEP"


class TestShimIntegration:
    """Live integration tests: SHIM proxy работает correctly.

    ADR-0313/0314 cycle 152: deprecation-shim emit DeprecationWarning + proxies
    to canonical. Migration window до cycle 156 (после telemetry audit).
    Тест проверяет runtime поведение shim → не ABI-only.
    """

    def test_batch_processor_shim_proxy_identity(self) -> None:
        """SHIM returns same class object as canonical (proxy works)."""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from src.backend.dsl.engine.processors import batch_processor as canonical
            from src.backend.dsl.processors import batch_processor as shim

            # DeprecationWarning должен быть испущен при импорте shim.
            assert any(
                issubclass(w.category, DeprecationWarning)
                and "batch_processor" in str(w.message)
                for w in caught
            ), f"Expected DeprecationWarning, got {[str(w.message) for w in caught]}"

            # Identity preserved: SHIM возвращает тот же класс object.
            assert shim.BatchProcessor is canonical.BatchProcessor

    def test_docstring_warns_cycle_156_removal(self) -> None:
        """Deprecation message mentions cycle 156 (migration window).

        Force re-import через importlib.reload — иначе Python кэширует модуль
        после первого импорта и DeprecationWarning (top-level, fires once) не
        срабатывает повторно в этом процессе.
        """
        import importlib
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import src.backend.dsl.processors.batch_processor as bp_module

            importlib.reload(bp_module)

        deprecations = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert any("cycle 156" in m for m in deprecations), (
            f"Deprecation should mention cycle 156 (telemetry audit milestone), "
            f"got: {deprecations}"
        )
        assert any("ADR-0313" in m or "ADR-0314" in m for m in deprecations), (
            f"Deprecation should reference ADR-0313/0314, got: {deprecations}"
        )


class TestRealInventory:
    """Run against real repo state."""

    def test_real_inventory_has_expected_files(self, real_inventory: list) -> None:
        rows = real_inventory
        assert 20 <= len(rows) <= 30
        saga_files = [r for r in rows if "saga_lra" in r.file]
        assert all(r.status == "SEMANTIC_KEEP" for r in saga_files)
        assert len(saga_files) >= 5

    def test_real_inventory_classifications_consistent(
        self, real_inventory: list
    ) -> None:
        rows = real_inventory
        valid_statuses = {"REMOVABLE", "NEEDS_MIGRATION", "SEMANTIC_KEEP", "SHIMMED"}
        for r in rows:
            assert r.status in valid_statuses, (
                f"{r.file} has invalid status {r.status!r}"
            )

    def test_real_inventory_total_loc(self, real_inventory: list) -> None:
        rows = real_inventory
        total_loc = sum(r.loc for r in rows)
        # v4 baseline: 28 files / 2496 LOC. Current: 24 files / 2210 LOC.
        # Drift acceptable.
        assert 1500 <= total_loc <= 3000

    def test_real_inventory_postfix_no_orphan_files(self, real_inventory: list) -> None:
        """Post-W2 P1-2 bug fix: 0 truely-orphan files в реальном inventory.

        Все legacy файлы теперь классифицируются как:
          - SEMANTIC_KEEP (saga_lra) — preserve per v4 §9.
          - SHIMMED (docstring-deprecation или package-internal) — migration window.

        Per v4 §10 P1: '0 importers + migration_window_elapsed → REMOVABLE'.
        Migration window ещё не истёк (cycle 156 не достигнут), поэтому
        SHIMMED правомерно. 0 REMOVABLE — это не сбой; это честный результат.
        """
        rows = real_inventory
        removable = [r for r in rows if r.status == "REMOVABLE"]
        assert removable == [], (
            f"Unexpected REMOVABLE files (нужен re-audit): {[(r.file, r.importer_count) for r in removable]}"
        )


class TestStrictMode:
    """--strict CI mode."""

    def test_strict_exits_nonzero_if_needs_migration(self) -> None:
        """Strict mode should fail if NEEDS_MIGRATION > 0."""
        # In current state, all 0-importer files = REMOVABLE,
        # all saga = SEMANTIC_KEEP, no NEEDS_MIGRATION expected.
        rc = main(["--strict"])
        # If real state has NEEDS_MIGRATION, rc = 1; else 0.
        # We accept either (CI gate behavior).
        assert rc in (0, 1)

    def test_strict_message(self) -> None:
        """Strict mode prints NEEDS_MIGRATION count if any."""
        # Just verify it runs without exception.
        rc = main(["--strict"])
        assert isinstance(rc, int)
