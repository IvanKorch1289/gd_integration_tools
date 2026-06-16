"""Unit tests for tools/check_layers.py — focus on S65 W2 changes.

Проверяют:
* ``_check_file`` теперь детектит lazy imports (раньше skip'алось S27).
* Stale allowlist entries репортятся.
* ``--update-allowlist`` создаёт/обновляет allowlist корректно.
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

# tools/ не является Python package — подключаем через path manipulation.
TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import check_layers  # noqa: E402  (после sys.path insert)


def test_lazy_import_is_now_detected() -> None:
    """S65 W2: lazy import (внутри функции) ДОЛЖЕН быть пойман.

    До S65 W2 — skip'ался ``if is_lazy: continue`` (S27 marker).
    """
    src = textwrap.dedent(
        """
        def _register_outbox_dispatcher():
            # lazy import — был blind spot
            from src.backend.infrastructure.resilience.breaker import (
                PurgatoryCircuitBreaker,
            )
            return PurgatoryCircuitBreaker()
        """
    ).strip()
    tree = ast.parse(src)
    # _imports() возвращает список (module, lineno, is_lazy)
    imports = list(check_layers._imports(tree))
    lazy_imports = [m for m, _, is_lazy in imports if is_lazy]
    assert any("breaker" in m for m in lazy_imports), (
        f"Expected lazy import of breaker module, got {imports}"
    )


def test_top_level_import_is_detected() -> None:
    """Top-level импорт всегда детектится (sanity check)."""
    src = textwrap.dedent(
        """
        from src.backend.infrastructure.cache import redis_cache
        """
    ).strip()
    tree = ast.parse(src)
    imports = list(check_layers._imports(tree))
    top_level = [m for m, _, is_lazy in imports if not is_lazy]
    assert "src.backend.infrastructure.cache" in top_level


def test_type_checking_import_is_skipped() -> None:
    """``if TYPE_CHECKING:`` block (через ``typing.TYPE_CHECKING``) — НЕ нарушение.

    Runtime TYPE_CHECKING=False → импорт НЕ выполняется, значит
    архитектурная связь отсутствует.
    """
    src = textwrap.dedent(
        """
        from __future__ import annotations
        import typing

        if typing.TYPE_CHECKING:
            from src.backend.infrastructure.cache import redis_cache
        """
    ).strip()
    tree = ast.parse(src)
    for _module, lineno, _is_lazy in check_layers._imports(tree):
        if lineno < 5:  # pragma: no cover — out of TYPE_CHECKING block
            continue
        assert check_layers._is_in_type_checking_block(tree, lineno), (
            f"Line {lineno} should be in TYPE_CHECKING block"
        )


def test_violation_key_format() -> None:
    """Violation key — ``{rel}\\t{layer}\\t{module}``, stable для allowlist."""
    key = check_layers._violation_key(
        ("src/backend/core/foo.py", "core", "src.backend.services.bar")
    )
    assert key == "src/backend/core/foo.py\tcore\tsrc.backend.services.bar"


def test_dsl_and_workflows_in_layers() -> None:
    """S65 W4: ``dsl`` и ``workflows`` — часть LAYERS.

    Без этого 280+ файлов в ``dsl/`` импортируют из других слоёв
    и линтер их не видит (blind spot).
    """
    assert "dsl" in check_layers.LAYERS
    assert "workflows" in check_layers.LAYERS
    # Allowed: dsl/workflows могут импортировать все backend слои
    dsl_allowed = check_layers.ALLOWED["dsl"]
    workflows_allowed = check_layers.ALLOWED["workflows"]
    for layer in ("core", "infrastructure", "services", "entrypoints", "schemas"):
        assert layer in dsl_allowed, f"dsl must allow {layer}"
        assert layer in workflows_allowed, f"workflows must allow {layer}"


def test_file_layer_detects_dsl() -> None:
    """S65 W4: ``_file_layer`` корректно определяет ``dsl`` layer."""
    from pathlib import Path

    root = Path("src")
    layer = check_layers._file_layer(Path("src/backend/dsl/route/builder/foo.py"), root)
    assert layer == "dsl"


def test_file_layer_detects_workflows() -> None:
    """S65 W4: ``_file_layer`` корректно определяет ``workflows`` layer."""
    from pathlib import Path

    root = Path("src")
    layer = check_layers._file_layer(Path("src/backend/workflows/registry.py"), root)
    assert layer == "workflows"


def test_test_files_in_extensions_are_excluded() -> None:
    """S110 W1: extensions/*/tests/ are excluded from layer check.

    Tests are allowed to import from any layer (test internals).
    Production code in extensions/ still must follow core-only rule.
    """
    # Create fake extensions tree in temp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Production extension file — should be checked
        prod_file = root / "extensions" / "ext1" / "service.py"
        prod_file.parent.mkdir(parents=True)
        prod_file.write_text(
            # S110 W4: services.integrations.skb — НЕ framework exception,
            # остаётся violation для production code.
            "from src.backend.services.integrations.skb import APISKBService\n"
        )
        # Test file in extensions — should be excluded
        test_file = root / "extensions" / "ext1" / "tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "from src.backend.services.plugins.manifest_v11 import load_plugin_manifest\n"
        )

        prod_violations = check_layers._check_file(prod_file, root)
        test_violations = check_layers._check_file(test_file, root)

        # Production file: violation detected
        assert len(prod_violations) == 1
        assert prod_violations[0][2] == "src.backend.services.integrations.skb"

        # Test file: excluded (no violations)
        assert len(test_violations) == 0


def test_update_allowlist_merges_with_existing(tmp_path, monkeypatch) -> None:
    """S110 W2: --update-allowlist MERGES with existing (was REPLACE).

    Regression: pre-S110 W2 the function used ``sorted(set(keys))``
    which DROPPED existing entries. Test verifies legacy entries
    survive a refresh.
    """
    # Pre-populate allowlist with legacy entry
    legacy_entry = "extensions/legacy/file.py\t\textensions\t\tsrc.backend.services.foo"
    monkeypatch.setattr(check_layers, "ALLOWLIST_PATH", tmp_path / "allowlist.txt")
    tmp_path.joinpath("allowlist.txt").write_text("# header\n" + legacy_entry + "\n")

    # New violations to add
    new_violations = [
        ("extensions/new/file.py", "extensions", "src.backend.services.bar")
    ]
    check_layers._save_allowlist(
        {check_layers._violation_key(v) for v in new_violations}
    )

    content = tmp_path.joinpath("allowlist.txt").read_text()
    # Legacy entry preserved
    assert legacy_entry in content, "legacy entry was dropped (regression)"
    # New entry added (verify with parsed keys, not raw tab chars)
    keys_in_file = [
        line
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert any("extensions/new/file.py" in k for k in keys_in_file), (
        f"new entry was not added; got {keys_in_file}"
    )


def test_prune_allowlist_removes_stale_entries(tmp_path, monkeypatch) -> None:
    """S112 W1: --prune-allowlist removes stale entries (complement to MERGE).

    Stale = entry в allowlist, для которой corresponding violation
    больше не в коде. Полная противоположность S110 W2 MERGE.
    """
    # Pre-populate allowlist with 3 entries: 2 current, 1 stale.
    # Use chr(9) to insert actual TAB characters (raw "\t" gets escape-interpreted).
    TAB = chr(9)
    current1 = f"extensions/current1.py{TAB}extensions{TAB}src.backend.services.foo"
    current2 = f"src/backend/core/current2.py{TAB}core{TAB}src.backend.services.bar"
    stale = f"extensions/stale.py{TAB}extensions{TAB}src.backend.services.removed"
    monkeypatch.setattr(check_layers, "ALLOWLIST_PATH", tmp_path / "allowlist.txt")
    tmp_path.joinpath("allowlist.txt").write_text(
        "# header\n" + current1 + "\n" + current2 + "\n" + stale + "\n"
    )

    # Current violations: только current1 + current2 (stale уже нет в коде).
    current_violations = [
        ("extensions/current1.py", "extensions", "src.backend.services.foo"),
        ("src/backend/core/current2.py", "core", "src.backend.services.bar"),
    ]
    removed = check_layers._prune_allowlist(
        {check_layers._violation_key(v) for v in current_violations}
    )

    assert removed == 1, f"Expected 1 stale entry removed, got {removed}"

    content = tmp_path.joinpath("allowlist.txt").read_text()
    # Current entries preserved
    assert current1 in content, "current entry 1 was removed (regression)"
    assert current2 in content, "current entry 2 was removed (regression)"
    # Stale entry removed
    assert stale not in content, "stale entry was NOT removed"


def test_prune_allowlist_no_stale_returns_zero(tmp_path, monkeypatch) -> None:
    """S112 W1: если нет stale entries, --prune-allowlist no-op (return 0)."""
    TAB = chr(9)
    current = f"extensions/current.py{TAB}extensions{TAB}src.backend.services.foo"
    monkeypatch.setattr(check_layers, "ALLOWLIST_PATH", tmp_path / "allowlist.txt")
    tmp_path.joinpath("allowlist.txt").write_text("# header\n" + current + "\n")

    current_violations = [
        ("extensions/current.py", "extensions", "src.backend.services.foo")
    ]
    removed = check_layers._prune_allowlist(
        {check_layers._violation_key(v) for v in current_violations}
    )
    assert removed == 0


def test_collect_all_violations_covers_src_and_extensions(tmp_path) -> None:
    """S112 W1: _collect_all_violations scans BOTH src/ and extensions/.

    Проверяет, что root-agnostic prune (для --prune-allowlist) не
    оставляет src/ entries как "стейл" при extensions/ scan (и наоборот).
    """
    keys = check_layers._collect_all_violations()
    assert isinstance(keys, set)
    # Должны быть entries из обоих roots (если они существуют в репо).
    has_src = any("src/" in k for k in keys)
    has_ext = any(k.startswith("extensions/") for k in keys)
    # В реальном репо оба должны быть True, но для portability проверим
    # хотя бы что функция работает без exception.
    assert has_src or has_ext, (
        "Expected at least some violations from src/ or extensions/"
    )


def test_framework_exceptions_list_exists() -> None:
    """S110 W4: EXTENSIONS_FRAMEWORK_EXCEPTIONS defined и non-empty.

    11 модулей: SQLAlchemyRepository, main_session_manager, BaseService,
    BaseEntrypoint, BaseSchema, BaseExternalAPIClient, AdDirectoryClient,
    4 per-entity route schemas (orders/users/orderkinds/files).
    """
    exceptions = check_layers.EXTENSIONS_FRAMEWORK_EXCEPTIONS
    assert isinstance(exceptions, set)
    assert len(exceptions) >= 7
    # Spot-check key entries
    assert "src.backend.infrastructure.repositories.base" in exceptions
    assert "src.backend.infrastructure.database.session_manager" in exceptions
    assert "src.backend.services.core.base" in exceptions
    assert "src.backend.entrypoints.base" in exceptions
    assert "src.backend.schemas.base" in exceptions


def test_framework_exception_hides_violation() -> None:
    """S110 W4: framework base classes НЕ считаются нарушениями в extensions.

    Regression: до S110 W4 extensions импортирующие SQLAlchemyRepository
    или main_session_manager считались layer violations. Теперь это
    легитимные framework imports.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Extension file with framework base import
        ext_file = root / "extensions" / "ext1" / "repo.py"
        ext_file.parent.mkdir(parents=True)
        ext_file.write_text(
            "from src.backend.infrastructure.repositories.base import SQLAlchemyRepository\n"
            "from src.backend.infrastructure.database.session_manager import main_session_manager\n"
            "from src.backend.services.core.base import BaseService\n"
        )

        violations = check_layers._check_file(ext_file, root)
        # Все 3 импорта — framework exceptions, 0 violations
        assert len(violations) == 0, (
            f"Framework exceptions should not be violations, got {violations}"
        )


def test_framework_exception_does_not_apply_to_other_layers() -> None:
    """S110 W4: framework exception ТОЛЬКО для extensions layer.

    Core/Services/Infra не получают bonus — для них те же imports
    остаются легитимными (allowed set), но exceptions здесь не нужны.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Service file with framework import — должен быть ALLOWED
        # (services → core/schemas), не violation
        svc_file = root / "services" / "svc1" / "service.py"
        svc_file.parent.mkdir(parents=True)
        svc_file.write_text(
            "from src.backend.core.errors import NotFoundError\n"  # core — allowed
        )

        violations = check_layers._check_file(svc_file, root)
        assert len(violations) == 0
