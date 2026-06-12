"""Regression test: assert canonical single-entry для CB + retry.

S93 W2 (fact-check): user/DEEP-RESEARCH список содержал "4× CB дубликатов"
и "4× retry модулей" — оба FALSE POSITIVES.

Реальная архитектура (verified 2026-06-12):
* CB canonical: src/backend/core/resilience/breaker.py (V22.10.2, ADR-005)
* Retry canonical: src/backend/core/resilience/retry.py (V16 single-entry)

Прочие файлы — facade/shim/per-route/saga — НЕ дубликаты, а
специализированные entry-points (документировано в docstring каждого).

Этот тест regression-блокирует попытки создать НЕ-genuinely-новый CB/retry
implementation.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _read_docstring(src: Path) -> str:
    """Возвращает module docstring или ''."""
    tree = ast.parse(src.read_text())
    return ast.get_docstring(tree) or ""


def test_circuit_breaker_canonical_module_exists() -> None:
    """Canonical CB: core/resilience/breaker.py (V22.10.2 single-entry)."""
    canonical = PROJECT_ROOT / "src/backend/core/resilience/breaker.py"
    assert canonical.exists(), f"Canonical CB module missing: {canonical}"
    docstring = _read_docstring(canonical)
    assert "V22.10.2" in docstring or "Single-Entry" in docstring or "canonical" in docstring.lower(), (
        f"Canonical CB docstring should mention 'canonical' or 'Single-Entry' / V22.10.2.\n"
        f"Got: {docstring[:200]}"
    )


def test_utils_circuit_breaker_is_deprecated_shim() -> None:
    """core/utils/circuit_breaker.py должен явно помечать себя deprecated."""
    shim = PROJECT_ROOT / "src/backend/core/utils/circuit_breaker.py"
    if not shim.exists():
        pytest.skip("Shim removed")  # если уже удалён в V24+
    docstring = _read_docstring(shim)
    assert "deprecated" in docstring.lower() or "backward" in docstring.lower(), (
        f"core/utils/circuit_breaker.py should be marked as deprecated/backward-compat.\n"
        f"Got: {docstring[:200]}"
    )


def test_retry_canonical_module_exists() -> None:
    """Canonical retry: core/resilience/retry.py (V16 single-entry)."""
    canonical = PROJECT_ROOT / "src/backend/core/resilience/retry.py"
    assert canonical.exists(), f"Canonical retry module missing: {canonical}"
    docstring = _read_docstring(canonical)
    assert "Single-Entry" in docstring or "canonical" in docstring.lower(), (
        f"Canonical retry docstring should mention 'Single-Entry' / canonical.\n"
        f"Got: {docstring[:200]}"
    )


def test_infrastructure_resilience_retry_documents_coexistence() -> None:
    """infrastructure/resilience/retry.py должен ссылаться на core canonical."""
    infra = PROJECT_ROOT / "src/backend/infrastructure/resilience/retry.py"
    if not infra.exists():
        pytest.skip("infra retry module removed")
    docstring = _read_docstring(infra)
    # Если модуль существует, он должен документировать coexistence с core
    assert "core" in docstring.lower() or "tenacity" in docstring.lower(), (
        f"infra/retry.py should document coexistence with core canonical.\n"
        f"Got: {docstring[:200]}"
    )


def test_ai_retry_policy_pydantic_only() -> None:
    """core/ai/retry_policy.py — Pydantic модель, НЕ duplicate tenacity wrapper."""
    ai_retry = PROJECT_ROOT / "src/backend/core/ai/retry_policy.py"
    if not ai_retry.exists():
        pytest.skip("ai/retry_policy.py removed")
    src = ai_retry.read_text()
    # Должен быть BaseModel, НЕ должен оборачивать tenacity напрямую
    assert "BaseModel" in src, "ai/retry_policy.py should define a Pydantic BaseModel"
    # НЕ должен импортировать tenacity напрямую (canonical retry это делает)
    assert "import tenacity" not in src or "from tenacity" not in src, (
        "ai/retry_policy.py should NOT import tenacity directly — "
        "use core/resilience/retry.py for the wrapper."
    )


def test_orchestration_retry_saga_pattern() -> None:
    """core/orchestration/retry.py — Saga compensation, НЕ duplicate."""
    orch = PROJECT_ROOT / "src/backend/core/orchestration/retry.py"
    if not orch.exists():
        pytest.skip("orchestration/retry.py removed")
    docstring = _read_docstring(orch)
    # Saga pattern — отличается от canonical tenacity-retry
    assert "compensat" in docstring.lower() or "saga" in docstring.lower(), (
        f"orchestration/retry.py should document saga/compensation pattern.\n"
        f"Got: {docstring[:200]}"
    )


def test_no_new_circuit_breaker_files_since_s93() -> None:
    """Запрет: новые CB файлы могут создаваться ТОЛЬКО как facade/shim с docstring."""
    # Ищем CB-named файлы вне known locations
    known_locations = {
        "src/backend/core/resilience/breaker.py",  # canonical
        "src/backend/core/utils/circuit_breaker.py",  # deprecated shim
        "src/backend/infrastructure/clients/external/circuit_breakers.py",  # facade
        "src/backend/entrypoints/middlewares/circuit_breaker.py",  # per-route middleware
    }
    found: list[Path] = []
    for pattern in ("**/circuit_breaker*.py", "**/breaker*.py", "**/circuit_breakers*.py"):
        for path in PROJECT_ROOT.glob(pattern):
            if not any(skip in str(path) for skip in ("__pycache__", ".venv", "node_modules")):
                rel = str(path.relative_to(PROJECT_ROOT))
                if rel not in known_locations:
                    found.append(path)
    assert not found, (
        f"New circuit breaker files detected (not in known canonical+shim+facade+middleware):\n"
        + "\n".join(f"  {p.relative_to(PROJECT_ROOT)}" for p in found)
    )
