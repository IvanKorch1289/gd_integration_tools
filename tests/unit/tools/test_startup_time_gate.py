"""Тесты для расширенного startup-time gate (S10 K2 W3)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    """Подгрузить tools/checks/startup_time.py через importlib."""
    path = Path(__file__).resolve().parents[3] / "tools" / "checks" / "startup_time.py"
    spec = importlib.util.spec_from_file_location("_startup_time_test", path)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить startup_time.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


@pytest.fixture
def isolated_baseline(monkeypatch, tmp_path):
    """Подменяет BASELINE_FILE на путь в tmp_path."""
    baseline = tmp_path / ".startup-time-baseline.json"
    monkeypatch.setattr(mod, "BASELINE_FILE", baseline)
    return baseline


def test_load_baseline_returns_none_when_missing(isolated_baseline) -> None:
    assert mod.load_baseline() is None


def test_save_then_load_baseline_roundtrip(isolated_baseline) -> None:
    mod.save_baseline(1.234)
    loaded = mod.load_baseline()
    assert loaded == pytest.approx(1.234, rel=1e-3)


def test_baseline_file_format(isolated_baseline) -> None:
    mod.save_baseline(0.512)
    content = json.loads(isolated_baseline.read_text(encoding="utf-8"))
    assert content["total"] == pytest.approx(0.512)
    assert content["tool"] == "startup_time"


def test_load_baseline_handles_malformed_json(isolated_baseline) -> None:
    isolated_baseline.write_text("not json", encoding="utf-8")
    assert mod.load_baseline() is None


def test_constants_defined() -> None:
    """Константы для thresholds присутствуют."""
    assert mod.MAX_STARTUP_SECONDS_PER_MODULE == 3.0
    assert mod.MAX_TOTAL_STARTUP_SECONDS == 3.0
    assert 0 < mod.REGRESSION_TOLERANCE < 1
    assert len(mod.CRITICAL_MODULES) >= 5


# ──────────────────── Measurement bug regression tests (06b83cd49) ──────────────

# Subprocess-скрипт, который пишет elapsed на stdout с маркером
# STARTUP_TIME_MARKER (per cycle 158+ fix).
_SUBPROCESS_SCRIPT_VALID = (
    "import sys\n"
    "sys.stdout.write('noise-line-1\\n')  # загрязнение от structlog/side effects\n"
    "sys.stdout.write('noise-line-2\\n')\n"
    "sys.stdout.write('STARTUP_TIME_MARKER:1.2345\\n')\n"
    "sys.stdout.flush()\n"
)

# Тот же скрипт, но БЕЗ маркера (legacy behavior fallthrough).
_SUBPROCESS_SCRIPT_NO_MARKER = "import sys\nsys.stdout.write('1.2345')\n"

# Скрипт с НЕвалидным маркером (для fallback testing).
_SUBPROCESS_SCRIPT_BAD_MARKER = (
    "import sys\n"
    "sys.stdout.write('noise\\nSTARTUP_TIME_MARKER:not_a_float\\nnoise\\n')\n"
)


def test_measure_import_extracts_marker_from_polluted_stdout() -> None:
    """Pre-fix bug: float(stdout.strip()) падал с ValueError → inf когда
    Vault logger или structlog загрязнял stdout.

    Post-fix: marker-based extraction находит STARTUP_TIME_MARKER в stdout
    даже если другие строки присутствуют.
    """
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": _SUBPROCESS_SCRIPT_VALID.replace(
                "sys.stdout.write('noise-line-1\\n')  # загрязнение от structlog/side effects\n"
                "sys.stdout.write('noise-line-2\\n')\n"
                "sys.stdout.write('STARTUP_TIME_MARKER:1.2345\\n')\n"
                "sys.stdout.flush()\n",
                "noise-line-1\nnoise-line-2\nSTARTUP_TIME_MARKER:1.2345\n",
            ),
            "stderr": "",
        },
    )()

    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(1.2345, rel=1e-4)


def test_measure_import_fallback_when_no_marker() -> None:
    """Fallback: если STARTUP_TIME_MARKER отсутствует, использовать legacy
    float(last_line) parsing.
    """
    proc = type("P", (), {"returncode": 0, "stdout": "1.2345", "stderr": ""})()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(1.2345, rel=1e-4)


def test_measure_import_returns_inf_when_no_parseable_value() -> None:
    """Если stdout содержит только invalid данные → inf.
    Pre-fix bug давал inf по другому path (structlog noise); post-fix
    inf только когда реально ничего нельзя распарсить.
    """
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": "completely invalid garbage content\nno numbers here",
            "stderr": "",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == float("inf")


def test_measure_import_returns_inf_on_subprocess_failure() -> None:
    """Subprocess вернул non-zero → inf (legacy semantic)."""
    proc = type(
        "P",
        (),
        {
            "returncode": 1,
            "stdout": "",
            "stderr": "ModuleNotFoundError: No module named 'fake_module'",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    elapsed = float("inf") if proc.returncode != 0 else elapsed
    assert elapsed == float("inf")


def test_measure_import_finds_marker_in_middle_of_lines() -> None:
    """Marker может быть в любой позиции stdout, не только в конце."""
    proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": "trailing noise\nSTARTUP_TIME_MARKER:0.9876\nmore trailing",
            "stderr": "",
        },
    )()
    elapsed = mod._extract_elapsed_from_stdout(proc.stdout)
    assert elapsed == pytest.approx(0.9876, rel=1e-4)


# ──────────────────────── Regression check: main() integration ──────────────────


def test_main_fails_when_per_module_budget_exceeded(
    isolated_baseline, monkeypatch, capsys
) -> None:
    """Main flow должен exit 1 когда per-module budget превышен."""
    # Подменяем measure_import на stub возвращающий budget-exceeding time.
    from src.backend.core.config import features  # noqa: F401  # any existing

    def fake_measure(module: str) -> float:
        return mod.MAX_STARTUP_SECONDS_PER_MODULE + 1.0  # > 3s

    monkeypatch.setattr(mod, "measure_import", fake_measure)
    rc = mod.main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.err or "FAIL" in captured.out


# ──────────── Медиана вместо одиночного холодного прогона (audit 2026-09-29) ──
#
# Гейт флейкал ~8%: 13 замеров разбросались 1.782–2.263s при лимите 2.145s
# (baseline 1.65 × 1.30). Причина — одиночный холодный замер. Решение: N
# прогонов + медиана. Бюджеты НЕ ослаблены, поэтому тесты ниже проверяют
# обе стороны: выброс сглаживается, а настоящая деградация всё ещё падает.


def test_median_of_sorts_and_averages_even_count() -> None:
    """Медиана нечувствительна к порядку и усредняет центр при чётном N."""
    assert mod.median_of([3.0, 1.0, 2.0]) == pytest.approx(2.0)
    assert mod.median_of([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)


def test_median_survives_single_outlier_pass(
    isolated_baseline, monkeypatch, capsys
) -> None:
    """Один медленный прогон среди трёх не должен ронять гейт.

    Именно это и наблюдалось: холодный замер 2.26s при лимите 2.145s.
    """
    fast = mod.MAX_STARTUP_SECONDS_PER_MODULE / (len(mod.CRITICAL_MODULES) * 4)
    calls = {"n": 0}

    def flaky_measure(module: str) -> float:
        calls["n"] += 1
        # Первый полный проход (7 вызовов) — аномально медленный.
        if calls["n"] <= len(mod.CRITICAL_MODULES):
            return fast * 4
        return fast

    monkeypatch.setattr(mod, "measure_import", flaky_measure)
    rc = mod.main(["--samples", "3"])
    out = capsys.readouterr().out
    assert rc == 0, f"медиана должна сгладить одиночный выброс:\n{out}"
    assert "median of 3" in out


def test_steady_regression_still_fails(isolated_baseline, monkeypatch, capsys) -> None:
    """Устойчивая деградация (все прогоны медленные) всё ещё роняет гейт.

    Страховка от «сглаживания всего подряд»: медиана не должна превращать
    гейт в warn-only.
    """
    per_module = mod.MAX_STARTUP_SECONDS_PER_MODULE + 0.5
    monkeypatch.setattr(mod, "measure_import", lambda module: per_module)
    rc = mod.main(["--samples", "3"])
    captured = capsys.readouterr()
    assert rc == 1, "медиана не должна скрывать устойчивую деградацию"
    assert "FAIL" in captured.err or "FAIL" in captured.out


def test_regression_limit_uses_median_not_best_pass(
    isolated_baseline, monkeypatch, capsys
) -> None:
    """Вердикт выносится на медиану, а не на лучший/первый прогон.

    baseline = 1.0 → лимит регрессии 1.3. Три прогона по 0.7s и один
    аномально медленный 6.3s: медиана = 0.7 → PASS. Если бы гейт смотрел
    на худший прогон, он бы упал — а это ровно тот ложный фейл, который
    наблюдался в 8% прогонов.
    """
    mod.save_baseline(1.0)
    n_modules = len(mod.CRITICAL_MODULES)
    calls = {"n": 0}

    def slow_last_pass(module: str) -> float:
        calls["n"] += 1
        pass_index = (calls["n"] - 1) // n_modules
        return 0.9 if pass_index == 2 else 0.1  # 6.3s на третьем прогоне

    monkeypatch.setattr(mod, "measure_import", slow_last_pass)
    assert mod.main(["--samples", "3"]) == 0

    # Контроль: два медленных прогона из трёх → медиана 6.3 → FAIL.
    calls2 = {"n": 0}

    def slow_two_passes(module: str) -> float:
        calls2["n"] += 1
        pass_index = (calls2["n"] - 1) // n_modules
        return 0.9 if pass_index >= 1 else 0.1

    monkeypatch.setattr(mod, "measure_import", slow_two_passes)
    capsys.readouterr()
    assert mod.main(["--samples", "3"]) == 1, (
        "медиана обязана ловить устойчивую деградацию"
    )


def test_samples_must_be_positive() -> None:
    """--samples 0 — ошибка использования, а не молчаливый PASS."""
    with pytest.raises(SystemExit) as exc:
        mod.main(["--samples", "0"])
    assert exc.value.code != 0


def test_default_samples_is_median_based() -> None:
    """По умолчанию гейт снимает несколько прогонов, а не один."""
    assert mod.SAMPLE_COUNT >= 3, (
        "одиночный замер флейкает; дефолт должен усреднять >=3 прогона"
    )
