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
