"""Sprint 4.1 — regression gate на удаление BatchingStructlogWrapper (YAGNI).

Cycle 1 P1-1 нашёл: BatchingStructlogWrapper мёртвый — ``bind_inner``
вызывался только из tests/, 0 production-caller'ов. Sprint 4.1 решил
удалить целиком (wrapper + flag + migration-tool entries).

Anti-regression gate:
  1. Модуль и его test-файл удалены с диска.
  2. Flag ``structlog_batching_enabled`` удалён из Sprint6Flags (20 fields).
  3. В ``src/backend/`` нет ссылок на удалённые symbols (anti-re-introduction).
  4. Migration-tools очищены.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SRC_BACKEND = _REPO_ROOT / "src" / "backend"
_TOOLS_DIR = _REPO_ROOT / "tools"

# Forbidden identifiers в production tree.
_FORBIDDEN_IDS = (
    r"\bBatchingStructlogWrapper\b",
    r"\bbind_inner\b",
    r"\bget_batching_wrapper\b",
    r"\bstructlog_batching_enabled\b",
)

_EXCLUDE_DIRS = frozenset({"__pycache__", ".venv", "venv", ".git", ".mypy_cache", ".ruff_cache"})


def _find_py_with_pattern(pattern: str, root: Path) -> list[Path]:
    """Рекурсивно ищет .py файлы под ``root`` (исключая служебные каталоги),
    в которых regex ``pattern`` имеет хотя бы одно совпадение.

    Pure-Python вместо subprocess+rg, чтобы не плодить зависимости
    в regression-тестах и не получать S603/S607 от ruff.
    """
    compiled = re.compile(pattern)
    hits: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if compiled.search(text):
            hits.append(path)
    return hits


def test_module_and_legacy_test_deleted() -> None:
    """structlog_batching.py + test_structlog_batching.py удалены."""
    assert not (_SRC_BACKEND / "observability" / "structlog_batching.py").exists()
    assert not (
        _REPO_ROOT / "tests" / "unit" / "infrastructure" / "observability"
        / "test_structlog_batching.py"
    ).exists()


def test_feature_flag_removed_from_sprint6() -> None:
    """structlog_batching_enabled удалён из Sprint6Flags (20 fields, не 21)."""
    from src.backend.core.config.features.sprint6 import Sprint6Flags

    fields = Sprint6Flags.model_fields
    assert "structlog_batching_enabled" not in fields
    assert len(fields) == 20


def test_no_production_imports_of_dead_symbols() -> None:
    """Anti-re-introduction: в src/backend/ нет ни одной ссылки на удалённые symbols."""
    for pattern in _FORBIDDEN_IDS:
        hits = _find_py_with_pattern(pattern, _SRC_BACKEND)
        assert not hits, (
            f"forbidden '{pattern}' re-introduced in src/backend: "
            f"{[str(h.relative_to(_REPO_ROOT)) for h in hits]}"
        )


def test_no_tool_whitelist_reference() -> None:
    """Migration-tools очищены от structlog_batching references."""
    for tool in (
        _TOOLS_DIR / "migrate_to_structlog.py",
        _TOOLS_DIR / "audit_stdlib_logging.py",
    ):
        content = tool.read_text(encoding="utf-8")
        assert "structlog_batching" not in content, (
            f"{tool.name}: stale structlog_batching reference"
        )
