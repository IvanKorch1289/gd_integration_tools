"""Meta-test: check_privacy_lifecycle default exit behavior (v6 W1).

Per v6 W1: «Любой backend с ❌ должен давать ненулевой exit code».
Раньше default mode (без --strict) exits 0 даже с ❌ — gate FAIL-OPEN.

Regression guard: проверяет что gate сейчас fail-closed by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_privacy_lifecycle.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_default_mode_exits_0_when_no_issues() -> None:
    """На текущем коде все 5 backends covered → exit 0 (no issues)."""
    result = _run()

    assert result.returncode == 0, (
        f"Default mode FAIL (exit={result.returncode}) but all 5 backends "
        f"have erasure. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Parse JSON output — должно показать все 5 backends как covered.
    result_json = _run("--json")
    payload = json.loads(result_json.stdout)
    backends = payload["storage_coverage"]
    assert len(backends) == 5, (
        f"Expected 5 backends, got {len(backends)}: {list(backends.keys())}"
    )
    uncovered = [name for name, info in backends.items() if not info["covered"]]
    assert not uncovered, f"Expected all 5 backends covered, uncovered: {uncovered}"


def test_default_mode_fails_on_synthetic_issue() -> None:
    """Воспроизводим ошибку: monkeypatched backends с ❌ → gate exits 1.

    Per v6 W1: «Любой backend с ❌ должен давать ненулевой exit code».
    """
    # Inject a fake broken state через временный файл — без permanent
    # damage. Простой подход: проверить что gate's exit logic корректен
    # через `_check_storage_coverage` direct call.
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.checks import check_privacy_lifecycle

        # Monkeypatch: forced uncovered.
        original = check_privacy_lifecycle._check_storage_coverage

        def broken_check():
            return {
                "fake_backend": {
                    "covered": False,
                    "evidence": "synthetic ❌ for meta-test",
                }
            }

        check_privacy_lifecycle._check_storage_coverage = broken_check
        try:
            result = check_privacy_lifecycle.main([])
            assert result == 1, f"Default gate SHOULD exit 1 per v6 W1, got {result}"
        finally:
            check_privacy_lifecycle._check_storage_coverage = original
    finally:
        sys.path.pop(0)


def test_no_strict_opt_out_for_debug() -> None:
    """--no-strict flag существует для opt-out (для triage / debugging)."""
    # Просто проверить что flag не падает на import.
    result = _run("--no-strict")
    assert result.returncode == 0, (
        f"--no-strict failed unexpectedly: {result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# ADR-0347: structural markers are NOT coverage
# ---------------------------------------------------------------------------


def test_every_backend_requires_a_behavioural_test() -> None:
    """Ни один backend не должен считаться covered без исполняющего теста.

    Исторически ``covered`` определялся поиском строк-"маркеров" в исходнике
    адаптера, поэтому нерабочий ``LangMemEpisodic.subject_id`` годами
    отчитывался как "✅ covered". Теперь у каждого backend есть
    ``_BEHAVIOURAL_TESTS`` + ``_ADAPTER_CLASS``, и gate обязан их требовать.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "tools" / "checks"))
    try:
        import check_privacy_lifecycle as g
    finally:
        sys.path.pop(0)

    assert set(g._BEHAVIOURAL_TESTS) == set(g._ADAPTER_CLASS), (
        "не все backends имеют behavioural-тест и adapter class"
    )
    for backend, tests in g._BEHAVIOURAL_TESTS.items():
        for rel in tests:
            path = PROJECT_ROOT / rel
            assert path.is_file(), f"{backend}: тест {rel} не найден"
            content = path.read_text(encoding="utf-8")
            assert g._ADAPTER_CLASS[backend] in content, (
                f"{backend}: {rel} не упоминает {g._ADAPTER_CLASS[backend]}"
            )
            assert ".execute(" in content, (
                f"{backend}: {rel} не исполняет adapter.execute()"
            )


def test_unresolvable_orm_attributes_are_detected() -> None:
    """Проверка ловит ссылки на несуществующие ORM-атрибуты.

    Это ровно тот дефект, что скрывался за маркерами: адаптер ссылался на
    ``LangMemEpisodic.subject_id``, которого в модели не было.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "tools" / "checks"))
    try:
        import check_privacy_lifecycle as g
    finally:
        sys.path.pop(0)

    models = g._load_orm_models()
    assert models, "ORM-модели должны импортироваться (иначе проверка фиктивна)"

    missing = g._unresolvable_model_attrs(
        "cond = LangMemEpisodic.definitely_not_a_column == 1", models
    )
    assert missing == ["LangMemEpisodic.definitely_not_a_column"]

    present = g._unresolvable_model_attrs("LangMemEpisodic.id == 1", models)
    assert present == []


def test_gate_is_fail_closed_when_models_not_importable(monkeypatch) -> None:
    """Невозможность импорта моделей → НЕ «проблем нет», а unverified."""
    sys.path.insert(0, str(PROJECT_ROOT / "tools" / "checks"))
    try:
        import check_privacy_lifecycle as g
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(g, "_load_orm_models", dict)
    backends = g._check_storage_coverage()
    assert backends
    assert all(b["covered"] is False for b in backends.values()), (
        "gate не должен считать backend покрытым, если проверить невозможно"
    )
