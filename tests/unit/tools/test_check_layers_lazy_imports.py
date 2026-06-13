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
    assert any(
        "breaker" in m for m in lazy_imports
    ), f"Expected lazy import of breaker module, got {imports}"


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
        assert check_layers._is_in_type_checking_block(
            tree, lineno
        ), f"Line {lineno} should be in TYPE_CHECKING block"


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
    layer = check_layers._file_layer(
        Path("src/backend/dsl/route/builder/foo.py"), root
    )
    assert layer == "dsl"


def test_file_layer_detects_workflows() -> None:
    """S65 W4: ``_file_layer`` корректно определяет ``workflows`` layer."""
    from pathlib import Path

    root = Path("src")
    layer = check_layers._file_layer(
        Path("src/backend/workflows/registry.py"), root
    )
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
            "from src.backend.infrastructure.database.session_manager import main_session_manager\n"
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
        assert prod_violations[0][2] == "src.backend.infrastructure.database.session_manager"

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
    tmp_path.joinpath("allowlist.txt").write_text(
        "# header\n" + legacy_entry + "\n"
    )

    # New violations to add
    new_violations = [
        ("extensions/new/file.py", "extensions", "src.backend.services.bar"),
    ]
    check_layers._save_allowlist(
        {check_layers._violation_key(v) for v in new_violations}
    )

    content = tmp_path.joinpath("allowlist.txt").read_text()
    # Legacy entry preserved
    assert legacy_entry in content, "legacy entry was dropped (regression)"
    # New entry added (verify with parsed keys, not raw tab chars)
    keys_in_file = [
        line for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert any("extensions/new/file.py" in k for k in keys_in_file), (
        f"new entry was not added; got {keys_in_file}"
    )
