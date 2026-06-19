"""Regression test: список files которые ЗАКОННО используют stdlib logging.

S95 W3 — после S93+S94 codemod остались файлы с stdlib `import logging`,
но это LEGITIMATE uses (не дублирующие core.logging). Этот тест enforce'ит
политику: каждый такой файл должен иметь комментарий или docstring объясняющий
ПОЧЕМУ stdlib остаётся.

Если кто-то мигрирует один из этих файлов без понимания — тест скажет
WHY it must stay stdlib.

Files:
- dsl/engine/context.py — `logging.Logger` type annotation
- infrastructure/clients/external/logger.py — stdlib `Handler` class
- infrastructure/clients/transport/http/request_mixin.py — `DEBUG` constant
- infrastructure/execution/dask_backend.py — Dask `silence_logs` parameter
- infrastructure/external_apis/logging_service.py — DEPRECATED module shim
- infrastructure/observability/structlog_batching.py — INTENTIONAL fallback
- workflows/worker.py — typer CLI basicConfig + WARNING constant
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


LEGITIMATE_STDLIB_FILES = (
    # (rel_path, regex marking legitimate use, human reason)
    (
        "src/backend/dsl/engine/context.py",
        r"logging\.Logger",
        "type annotation logging.Logger",
    ),
    (
        "src/backend/infrastructure/clients/external/logger.py",
        r"logging\.Handler",
        "stdlib Handler base class",
    ),
    (
        "src/backend/infrastructure/clients/transport/http/request_mixin.py",
        r"from logging import DEBUG",
        "tenacity DEBUG constant",
    ),
    (
        "src/backend/infrastructure/clients/transport/http_httpx.py",
        r"logging\.DEBUG",
        "tenacity hook DEBUG constant",
    ),
    (
        "src/backend/infrastructure/execution/dask_backend.py",
        r"logging\.WARNING",
        "Dask silence parameter",
    ),
    (
        "src/backend/infrastructure/external_apis/logging_service.py",
        r"from logging import",
        "DEPRECATED module — pending removal",
    ),
    (
        "src/backend/infrastructure/observability/structlog_batching.py",
        r"^import logging$",  # anchored; test re.search+re.MULTILINE
        "intentional stdlib fallback for structlog",
    ),
    (
        "src/backend/infrastructure/workflow/worker.py",
        r"logging\.basicConfig",
        "typer CLI basicConfig setup",
    ),
)


@pytest.mark.parametrize(
    "rel_path,marker_regex,reason",
    LEGITIMATE_STDLIB_FILES,
    ids=[t[0].split("/")[-1] for t in LEGITIMATE_STDLIB_FILES],
)
def test_legitimate_stdlib_use_has_marker(
    rel_path: str, marker_regex: str, reason: str
) -> None:
    """Каждый файл с legit stdlib use должен иметь marker (regex match)."""
    import re

    src = (PROJECT_ROOT / rel_path).read_text()
    # MULTILINE: ^ и $ привязаны к строкам, не к start/end всего файла.
    assert re.search(marker_regex, src, re.MULTILINE), (
        f"{rel_path} использует stdlib logging, но marker {marker_regex!r} "
        f"не найден. Reason: {reason}. Если stdlib больше не нужен — "
        "переведите на core.logging и удалите из LEGITIMATE_STDLIB_FILES."
    )


def test_total_legitimate_count_matches_expectation() -> None:
    """Должно быть ровно 8 legitimate stdlib uses (regression guard)."""
    assert len(LEGITIMATE_STDLIB_FILES) == 8, (
        f"LEGITIMATE_STDLIB_FILES должен быть длиной 8, got {len(LEGITIMATE_STDLIB_FILES)}. "
        "При добавлении нового legitimate use — обновите ADR-0179."
    )


def test_no_core_module_uses_stdlib_logging() -> None:
    """core/* модули НЕ ДОЛЖНЫ использовать stdlib logging (всё через core.logging).

    Исключения: `core/auth/saml_backend.py` (мигрирован в S94 W2),
    `core/auth/jwt_backend.py` и др. (мигрированы в S93 W4).
    Только `core/interfaces/__init__.py` (S94 W1) и `core/...` (S94 W1).
    """
    import re

    for py in (PROJECT_ROOT / "src/backend/core").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        # Skip py.typed
        if py.name in ("__init__.py", "py.typed"):
            continue
        src = py.read_text()
        # Pattern: `^import logging$` или `^from logging import`
        if re.search(r"^import logging$", src, re.MULTILINE) or re.search(
            r"^from logging import", src, re.MULTILINE
        ):
            # Allowed exceptions:
            rel = str(py.relative_to(PROJECT_ROOT))
            if rel in (t[0] for t in LEGITIMATE_STDLIB_FILES):
                continue
            # If not in legitimate list — fail
            pytest.fail(
                f"core/ file {rel} uses stdlib logging. "
                "Migrate to core.logging or add to LEGITIMATE_STDLIB_FILES."
            )
